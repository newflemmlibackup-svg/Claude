"""Durchsucht ein Quellverzeichnis (z. B. einen fremden USB-Stick) rekursiv nach
DICOM-Bilddateien und gruppiert sie zu Serien, unabhaengig von Dateiendung oder
Ordnerstruktur. Liest dabei nur die Header (keine Pixeldaten) fuer Geschwindigkeit.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import pydicom

# Unkomprimierte Standard-Transfersyntaxen, die praktisch jeder Viewer lesen kann.
UNCOMPRESSED_TRANSFER_SYNTAXES = {
    "1.2.840.10008.1.2",     # Implicit VR Little Endian
    "1.2.840.10008.1.2.1",   # Explicit VR Little Endian
    "1.2.840.10008.1.2.2",   # Explicit VR Big Endian (veraltet, aber unkomprimiert)
}

PLAUSIBLE_VOLUME_MODALITIES = {"CT"}


@dataclass
class SeriesInfo:
    """Eine erkannte Bildserie (i. d. R. ein DVT-Volumen) im Quellverzeichnis."""

    key: str
    study_uid: Optional[str]
    series_uid: Optional[str]
    patient_name: str
    patient_id: str
    modality: str
    series_description: str
    rows: int
    columns: int
    transfer_syntax: str
    is_compressed: bool
    file_paths: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def num_slices(self) -> int:
        return len(self.file_paths)

    @property
    def display_label(self) -> str:
        desc = f" - {self.series_description}" if self.series_description else ""
        return f"{self.patient_name} ({self.patient_id}) | {self.modality}{desc} | {self.num_slices} Bilder"


@dataclass
class ScanResult:
    series: list
    skipped_files: int
    total_files_seen: int


def _sort_key(ds) -> tuple:
    inst_no = ds.get("InstanceNumber", None)
    try:
        inst_no = int(inst_no) if inst_no not in (None, "") else None
    except (ValueError, TypeError):
        inst_no = None

    pos = ds.get("ImagePositionPatient", None)
    try:
        z = float(pos[2]) if pos is not None and len(pos) == 3 else None
    except (ValueError, TypeError, IndexError):
        z = None

    slice_loc = ds.get("SliceLocation", None)
    try:
        slice_loc = float(slice_loc) if slice_loc not in (None, "") else None
    except (ValueError, TypeError):
        slice_loc = None

    # Bevorzugte Reihenfolge: InstanceNumber, sonst raeumliche Position, sonst SliceLocation.
    return (
        0 if inst_no is not None else 1,
        inst_no if inst_no is not None else 0,
        0 if z is not None else 1,
        z if z is not None else 0.0,
        0 if slice_loc is not None else 1,
        slice_loc if slice_loc is not None else 0.0,
    )


def scan_source(source_dir, progress_cb: Optional[Callable[[str], None]] = None) -> ScanResult:
    """Durchsucht `source_dir` rekursiv und liefert ein ScanResult mit gefundenen Serien."""
    source_dir = Path(source_dir)
    groups: dict = {}
    total_seen = 0
    skipped = 0

    for root, _dirs, files in os.walk(source_dir):
        for fname in files:
            path = Path(root) / fname
            if fname.upper() == "DICOMDIR":
                continue

            total_seen += 1
            try:
                ds = pydicom.dcmread(str(path), force=True, stop_before_pixels=True)
            except Exception:
                skipped += 1
                continue

            if "Rows" not in ds or "Columns" not in ds:
                # Kein Bild (z.B. Strukturbericht, defekte Datei, Fremdformat) -> ueberspringen.
                skipped += 1
                continue

            study_uid = getattr(ds, "StudyInstanceUID", None)
            series_uid = getattr(ds, "SeriesInstanceUID", None)

            if study_uid and series_uid:
                key = ("UID", str(study_uid), str(series_uid))
            else:
                # Fallback, wenn UIDs fehlen: nach Ordner gruppieren (typisch bei
                # einfachen DVT-Exporten, die einen Ordner pro Volumen anlegen).
                key = ("DIR", str(path.parent))

            if key not in groups:
                ts = ""
                if hasattr(ds, "file_meta") and "TransferSyntaxUID" in ds.file_meta:
                    ts = str(ds.file_meta.TransferSyntaxUID)
                groups[key] = {
                    "study_uid": str(study_uid) if study_uid else None,
                    "series_uid": str(series_uid) if series_uid else None,
                    "patient_name": str(getattr(ds, "PatientName", "")).strip() or "Unbekannt",
                    "patient_id": str(getattr(ds, "PatientID", "")).strip() or "UNBEKANNT",
                    "modality": str(getattr(ds, "Modality", "")).strip(),
                    "series_description": str(getattr(ds, "SeriesDescription", "")).strip(),
                    "rows": int(getattr(ds, "Rows", 0)),
                    "columns": int(getattr(ds, "Columns", 0)),
                    "transfer_syntax": ts,
                    "items": [],
                }

            groups[key]["items"].append((_sort_key(ds), path))

            if progress_cb:
                progress_cb(f"{len(groups)} Serie(n) erkannt, {total_seen} Dateien gelesen ...")

    series_list = []
    for key, info in groups.items():
        warnings = []
        if not info["study_uid"]:
            warnings.append("Keine Study-UID gefunden - wird neu erzeugt")
        if not info["series_uid"]:
            warnings.append("Keine Series-UID gefunden - wird neu erzeugt")
        if info["modality"] not in PLAUSIBLE_VOLUME_MODALITIES:
            warnings.append(
                f"Modality '{info['modality'] or '(leer)'}' unueblich fuer ein DVT-Volumen - wird auf CT gesetzt"
            )
        ts = info["transfer_syntax"]
        compressed = bool(ts) and ts not in UNCOMPRESSED_TRANSFER_SYNTAXES
        if compressed:
            warnings.append(f"Komprimierte Bilddaten (Transfersyntax {ts}) - werden verlustfrei dekomprimiert")
        if info["patient_id"] == "UNBEKANNT":
            warnings.append("Keine Patienten-ID im DICOM-Header gefunden")
        if info["rows"] <= 1 or info["columns"] <= 1:
            warnings.append("Ungewoehnliche Bildgroesse - bitte Ergebnis pruefen")

        items = sorted(info["items"], key=lambda t: t[0])
        file_paths = [p for _sk, p in items]

        series_list.append(
            SeriesInfo(
                key="|".join(key),
                study_uid=info["study_uid"],
                series_uid=info["series_uid"],
                patient_name=info["patient_name"],
                patient_id=info["patient_id"],
                modality=info["modality"] or "CT",
                series_description=info["series_description"],
                rows=info["rows"],
                columns=info["columns"],
                transfer_syntax=ts,
                is_compressed=compressed,
                file_paths=file_paths,
                warnings=warnings,
            )
        )

    series_list.sort(key=lambda s: (s.patient_id, s.study_uid or "", s.series_uid or ""))

    return ScanResult(series=series_list, skipped_files=skipped, total_files_seen=total_seen)
