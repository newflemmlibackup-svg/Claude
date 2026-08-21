"""Ablage der Behandlungsplaene als Ordnerstruktur:

<Praxis-Datenordner>/
  Mustermann_Erika_2026-08-21_1430/
    opg.png
    plan.json

Ein Plan ist damit vollstaendig eigenstaendig (Bild + Planung) und laesst
sich einfach kopieren/sichern/verschicken.
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image

from .models import TreatmentPlan

PLAN_FILENAME = "plan.json"
IMAGE_FILENAME = "opg.png"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
DICOM_EXTENSIONS = {".dcm", ""}


def _sanitize(text: str, fallback: str = "Patient") -> str:
    text = (text or "").strip()
    text = re.sub(r"[^\w\-]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or fallback


def suggest_folder_name(patient_name: str, plan_date: str) -> str:
    safe_name = _sanitize(patient_name)
    safe_date = _sanitize(plan_date) or datetime.now().strftime("%Y-%m-%d")
    return f"{safe_name}_{safe_date}"


def _unique_folder(root_dir: Path, base_name: str) -> Path:
    candidate = root_dir / base_name
    counter = 2
    while candidate.exists():
        candidate = root_dir / f"{base_name}_{counter}"
        counter += 1
    return candidate


def create_plan_folder(root_dir, plan: TreatmentPlan) -> Path:
    root_dir = Path(root_dir)
    root_dir.mkdir(parents=True, exist_ok=True)
    base_name = suggest_folder_name(plan.patient_name, plan.plan_date)
    folder = _unique_folder(root_dir, base_name)
    folder.mkdir(parents=True)
    return folder


def _looks_like_dicom(path: Path) -> bool:
    if path.suffix.lower() == ".dcm":
        return True
    if path.suffix.lower() in IMAGE_EXTENSIONS:
        return False
    # Keine/unbekannte Endung: anhand der Datei-Signatur pruefen ("DICM" bei
    # Offset 128) oder versuchsweise mit pydicom lesen.
    try:
        with open(path, "rb") as fh:
            header = fh.read(132)
        if len(header) >= 132 and header[128:132] == b"DICM":
            return True
    except OSError:
        return False
    try:
        import pydicom

        pydicom.dcmread(str(path), force=True, stop_before_pixels=True)
        return True
    except Exception:
        return False


def _load_dicom_as_pil(path: Path) -> Image.Image:
    import numpy as np
    import pydicom

    try:
        from pydicom.pixels import apply_voi_lut
    except ImportError:  # aeltere pydicom-Version
        from pydicom.pixel_data_handlers.util import apply_voi_lut

    ds = pydicom.dcmread(str(path), force=True)
    arr = ds.pixel_array
    if arr.ndim == 3 and "NumberOfFrames" in ds and int(ds.NumberOfFrames) > 1:
        arr = arr[0]  # OPGs sind Einzelbilder - zur Sicherheit nur erstes Frame

    try:
        arr = apply_voi_lut(arr, ds)
    except Exception:
        pass

    arr = arr.astype("float64")
    if str(getattr(ds, "PhotometricInterpretation", "")) == "MONOCHROME1":
        arr = arr.max() - arr

    lo, hi = arr.min(), arr.max()
    if hi > lo:
        arr = (arr - lo) / (hi - lo) * 255.0
    else:
        arr = arr * 0.0
    arr = arr.astype("uint8")
    return Image.fromarray(arr).convert("L").convert("RGB")


def import_image(source_path, dest_folder) -> tuple:
    """Kopiert/konvertiert das OPG-Quellbild nach `dest_folder/opg.png`.

    Unterstuetzt gaengige Bildformate sowie DICOM (Einzelbild). Gibt
    (dateiname, breite_px, hoehe_px) zurueck.
    """
    source_path = Path(source_path)
    dest_folder = Path(dest_folder)
    dest_path = dest_folder / IMAGE_FILENAME

    if _looks_like_dicom(source_path):
        img = _load_dicom_as_pil(source_path)
    else:
        img = Image.open(source_path)
        img = img.convert("RGB")

    img.save(dest_path, "PNG")
    return IMAGE_FILENAME, img.width, img.height


def save_plan(plan: TreatmentPlan, folder) -> Path:
    folder = Path(folder)
    plan.touch()
    plan_path = folder / PLAN_FILENAME
    tmp_path = plan_path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(plan.to_dict(), fh, indent=2, ensure_ascii=False)
    tmp_path.replace(plan_path)
    return plan_path


def load_plan(folder) -> TreatmentPlan:
    folder = Path(folder)
    with open(folder / PLAN_FILENAME, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return TreatmentPlan.from_dict(data)


@dataclass
class PlanSummary:
    folder: Path
    patient_name: str
    plan_date: str
    practitioner: str
    item_count: int
    total_cost: float
    updated_at: str


def list_plans(root_dir) -> list:
    root_dir = Path(root_dir)
    if not root_dir.exists():
        return []
    summaries = []
    for entry in sorted(root_dir.iterdir()):
        plan_path = entry / PLAN_FILENAME
        if not entry.is_dir() or not plan_path.exists():
            continue
        try:
            with open(plan_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        items = data.get("items", [])
        summaries.append(PlanSummary(
            folder=entry,
            patient_name=data.get("patient_name", "") or "(ohne Namen)",
            plan_date=data.get("plan_date", ""),
            practitioner=data.get("practitioner", ""),
            item_count=len(items),
            total_cost=sum(i.get("cost", 0.0) for i in items),
            updated_at=data.get("updated_at", ""),
        ))
    summaries.sort(key=lambda s: s.updated_at, reverse=True)
    return summaries


def duplicate_plan(source_folder, root_dir, new_plan_date: Optional[str] = None) -> Path:
    """Legt einen neuen Plan mit demselben Bild und denselben Positionen an
    (z. B. fuer einen Folgetermin). Der neue Plan bekommt eine eigene ID."""
    source_folder = Path(source_folder)
    plan = load_plan(source_folder)
    plan.plan_id = TreatmentPlan().plan_id
    if new_plan_date:
        plan.plan_date = new_plan_date
    dest_folder = create_plan_folder(root_dir, plan)
    shutil.copy2(source_folder / plan.image_filename, dest_folder / plan.image_filename)
    save_plan(plan, dest_folder)
    return dest_folder


def delete_plan(folder) -> None:
    shutil.rmtree(Path(folder))
