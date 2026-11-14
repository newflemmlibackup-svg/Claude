"""Durchsucht einen Quellordner (z. B. einen fremden USB-Stick) nach DICOM-Bildern.

Es werden nur die Header gelesen (keine Pixeldaten). Zusammengehörige Schichten
werden zu Serien gruppiert - unabhängig von Dateinamen, Endungen oder
Ordnerstruktur. Für jedes DVT-Volumen wird ein Schichtplan berechnet, der die
Reihenfolge festlegt und fehlende Schichten als Lücken ausweist.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import pydicom

from .volume import SliceRef, VolumePlan, build_plan

UNCOMPRESSED_TRANSFER_SYNTAXES = {
    "1.2.840.10008.1.2",     # Implicit VR Little Endian
    "1.2.840.10008.1.2.1",   # Explicit VR Little Endian
    "1.2.840.10008.1.2.2",   # Explicit VR Big Endian
}

# Dateien, die sicher keine DICOM-Bilder sind (Viewer-Programme auf dem Stick usw.).
_SKIP_EXTENSIONS = {
    ".exe", ".dll", ".msi", ".bat", ".cmd", ".com", ".sys", ".inf", ".ini", ".lnk",
    ".txt", ".pdf", ".htm", ".html", ".xml", ".json", ".css", ".js", ".chm", ".rtf",
    ".doc", ".docx", ".xls", ".xlsx", ".csv", ".log", ".md",
    ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".ico", ".svg",
    ".zip", ".rar", ".7z", ".gz", ".tar", ".iso", ".cab", ".jar",
    ".mp4", ".avi", ".mov", ".wmv", ".mp3", ".wav",
    ".stl", ".ply", ".obj", ".db", ".sqlite", ".dat_", ".app", ".dmg", ".pkg",
    ".ds_store", ".plist", ".py", ".pyc",
}
_SKIP_DIRS = {
    "$recycle.bin", "system volume information", ".spotlight-v100", ".trashes",
    ".fseventsd", ".temporaryitems", "__macosx",
}

# Ab so vielen Schichten gilt eine Graustufen-Serie als 3D-Volumen.
MIN_VOLUME_SLICES = 5

KIND_VOLUME = "volume"
KIND_IMAGES = "images"


@dataclass
class PatientData:
    """Vom Anwender editierbare Angaben, die in die Ausgabe geschrieben werden."""

    last_name: str = ""
    first_name: str = ""
    birth_date: str = ""      # JJJJMMTT oder leer
    sex: str = ""             # M, F, O oder leer
    patient_id: str = ""
    study_date: str = ""      # JJJJMMTT oder leer
    description: str = ""

    def copy(self) -> "PatientData":
        return PatientData(**self.__dict__)

    @property
    def display_name(self) -> str:
        name = ", ".join(p for p in (self.last_name, self.first_name) if p)
        return name or "(ohne Namen)"


@dataclass
class SeriesInfo:
    """Eine erkannte Bildserie - in der Regel ein DVT-Volumen."""

    key: str
    kind: str
    patient: PatientData
    source_study_uid: str
    modality: str
    manufacturer: str
    model: str
    rows: int
    columns: int
    transfer_syntax: str
    is_compressed: bool
    slices: list = field(default_factory=list)       # list[SliceRef]
    plan: Optional[VolumePlan] = None                # nur bei kind == volume
    warnings: list = field(default_factory=list)
    source_dir: str = ""

    @property
    def num_found(self) -> int:
        return self.plan.num_found if self.plan else len(self.slices)

    @property
    def num_missing(self) -> int:
        return self.plan.num_missing if self.plan else 0

    @property
    def num_output(self) -> int:
        return len(self.plan.slots) if self.plan else len(self.slices)

    @property
    def size_label(self) -> str:
        return f"{self.columns} × {self.rows} × {self.num_output}"

    @property
    def display_label(self) -> str:
        typ = "DVT-Volumen" if self.kind == KIND_VOLUME else "Einzelbild(er)"
        return f"{self.patient.display_name} | {typ} | {self.size_label}"


@dataclass
class ScanResult:
    series: list
    skipped_files: int
    total_files_seen: int


def _text(value) -> str:
    if value is None:
        return ""
    try:
        return str(value).strip().strip("\x00").strip()
    except Exception:  # noqa: BLE001
        return ""


def _date(value) -> str:
    digits = re.sub(r"\D", "", _text(value))
    return digits[:8] if len(digits) >= 8 else ""


def _int(value) -> Optional[int]:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _floats(value, n: int) -> Optional[tuple]:
    try:
        vals = tuple(float(v) for v in value)
    except (TypeError, ValueError):
        return None
    return vals if len(vals) == n else None


def _split_name(pn) -> tuple:
    """DICOM-Personenname ('Nachname^Vorname') in (Nachname, Vorname) zerlegen."""
    raw = _text(pn)
    if not raw:
        return "", ""
    if "^" in raw:
        parts = raw.split("=")[0].split("^")
        return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")
    if "," in raw:
        last, first = raw.split(",", 1)
        return last.strip(), first.strip()
    return raw, ""


def _looks_like_dicom(path: Path) -> Optional[bool]:
    """True: sicher DICOM (Präambel). None: unklar, Versuch lohnt. False: sicher nicht."""
    try:
        size = path.stat().st_size
        if size < 64:
            return False
        with open(path, "rb") as fh:
            head = fh.read(132)
    except OSError:
        return False
    if len(head) >= 132 and head[128:132] == b"DICM":
        return True
    if path.suffix.lower() in _SKIP_EXTENSIONS:
        return False
    # Ohne Präambel: Datei muss mit einem plausiblen DICOM-Tag beginnen.
    groups = (0x0002, 0x0008, 0x0010, 0x0018, 0x0020, 0x0028)
    if int.from_bytes(head[:2], "little") in groups or int.from_bytes(head[:2], "big") in groups:
        return None
    return False


def _frame_geometry(ds, frame_index: int):
    """Position/Orientierung/Abstände eines Frames aus Multiframe-Sequenzen lesen."""
    pos = iop = spacing = thickness = None
    for seq_name, idx in (("PerFrameFunctionalGroupsSequence", frame_index),
                          ("SharedFunctionalGroupsSequence", 0)):
        try:
            item = ds[seq_name].value[idx]
        except Exception:  # noqa: BLE001
            continue
        try:
            if pos is None:
                pos = _floats(item.PlanePositionSequence[0].ImagePositionPatient, 3)
        except Exception:  # noqa: BLE001
            pass
        try:
            if iop is None:
                iop = _floats(item.PlaneOrientationSequence[0].ImageOrientationPatient, 6)
        except Exception:  # noqa: BLE001
            pass
        try:
            pm = item.PixelMeasuresSequence[0]
            if spacing is None:
                spacing = _floats(pm.get("PixelSpacing"), 2)
            if thickness is None:
                thickness = _floats([pm.get("SpacingBetweenSlices") or pm.get("SliceThickness")], 1)
        except Exception:  # noqa: BLE001
            pass
    return pos, iop, spacing, thickness[0] if thickness else None


def _read_header(path: Path):
    kind = _looks_like_dicom(path)
    if kind is False:
        return None
    try:
        ds = pydicom.dcmread(str(path), force=True, stop_before_pixels=True)
    except Exception:  # noqa: BLE001
        return None
    rows, cols = _int(ds.get("Rows")), _int(ds.get("Columns"))
    if not rows or not cols or rows < 2 or cols < 2 or rows > 20000 or cols > 20000:
        return None
    return ds


def scan_source(source_dir, progress_cb: Optional[Callable[[str], None]] = None) -> ScanResult:
    """Durchsucht `source_dir` rekursiv und liefert die gefundenen Serien."""
    source_dir = Path(source_dir)
    groups: dict = {}
    total_seen = 0
    skipped = 0

    for root, dirs, files in os.walk(source_dir, onerror=lambda e: None):
        dirs[:] = sorted(d for d in dirs if d.lower() not in _SKIP_DIRS)
        for fname in sorted(files):
            if fname.upper() == "DICOMDIR" or fname.startswith("._"):
                continue
            path = Path(root) / fname
            total_seen += 1
            if progress_cb and total_seen % 25 == 0:
                progress_cb(f"{total_seen} Dateien geprüft, {len(groups)} Serie(n) erkannt …")

            ds = _read_header(path)
            if ds is None:
                skipped += 1
                continue

            rows, cols = int(ds.Rows), int(ds.Columns)
            frames = _int(ds.get("NumberOfFrames")) or 1
            samples = _int(ds.get("SamplesPerPixel")) or 1
            study_uid = _text(ds.get("StudyInstanceUID"))
            series_uid = _text(ds.get("SeriesInstanceUID"))
            iop = _floats(ds.get("ImageOrientationPatient"), 6)
            iop_key = tuple(round(v, 2) for v in iop) if iop else None

            if frames > 1:
                # Jede Multiframe-Datei ist ein eigenes Volumen.
                key = ("MF", str(path))
            elif series_uid:
                key = ("UID", study_uid, series_uid, rows, cols, samples, iop_key)
            else:
                key = ("DIR", str(path.parent), rows, cols, samples, iop_key)

            g = groups.get(key)
            if g is None:
                ts = ""
                try:
                    ts = _text(ds.file_meta.get("TransferSyntaxUID"))
                except Exception:  # noqa: BLE001
                    pass
                last, first = _split_name(ds.get("PatientName"))
                sex = _text(ds.get("PatientSex")).upper()[:1]
                g = groups[key] = {
                    "patient": PatientData(
                        last_name=last,
                        first_name=first,
                        birth_date=_date(ds.get("PatientBirthDate")),
                        sex=sex if sex in ("M", "F", "O") else "",
                        patient_id=_text(ds.get("PatientID")),
                        study_date=_date(ds.get("StudyDate")) or _date(ds.get("SeriesDate"))
                        or _date(ds.get("AcquisitionDate")) or _date(ds.get("ContentDate")),
                        description=_text(ds.get("SeriesDescription")) or _text(ds.get("StudyDescription")),
                    ),
                    "study_uid": study_uid,
                    "has_series_uid": bool(series_uid),
                    "modality": _text(ds.get("Modality")),
                    "manufacturer": _text(ds.get("Manufacturer")),
                    "model": _text(ds.get("ManufacturerModelName")),
                    "rows": rows, "cols": cols, "samples": samples,
                    "ts": ts, "dir": str(path.parent),
                    "slices": [], "iops": [], "pix": [], "thick": [],
                }

            if frames > 1:
                for f in range(frames):
                    pos, f_iop, f_sp, f_th = _frame_geometry(ds, f)
                    g["slices"].append(SliceRef(path=path, frame=f, instance_number=f + 1, position=pos))
                    if f_iop:
                        g["iops"].append(f_iop)
                    if f_sp:
                        g["pix"].append(f_sp)
                    if f_th:
                        g["thick"].append(f_th)
                top_pos = _floats(ds.get("ImagePositionPatient"), 3)
                if top_pos and all(s.position is None for s in g["slices"]):
                    g["top_pos"] = top_pos
            else:
                g["slices"].append(SliceRef(
                    path=path, frame=None,
                    instance_number=_int(ds.get("InstanceNumber")),
                    position=_floats(ds.get("ImagePositionPatient"), 3),
                ))

            if iop:
                g["iops"].append(iop)
            sp = _floats(ds.get("PixelSpacing"), 2) or _floats(ds.get("ImagerPixelSpacing"), 2)
            if sp:
                g["pix"].append(sp)
            th = _floats([ds.get("SpacingBetweenSlices") or ds.get("SliceThickness")], 1)
            if th and th[0] > 0:
                g["thick"].append(th[0])

    series_list = []
    for key, g in groups.items():
        warnings = []
        ts = g["ts"]
        compressed = bool(ts) and ts not in UNCOMPRESSED_TRANSFER_SYNTAXES
        is_volume = g["samples"] == 1 and len(g["slices"]) >= MIN_VOLUME_SLICES

        plan = None
        if is_volume:
            iop = Counter(tuple(round(v, 4) for v in i) for i in g["iops"]).most_common(1)
            pix = Counter(tuple(round(v, 5) for v in p) for p in g["pix"]).most_common(1)
            thick = Counter(round(t, 5) for t in g["thick"]).most_common(1)
            plan = build_plan(
                g["slices"],
                iop=iop[0][0] if iop else None,
                pixel_spacing=pix[0][0] if pix else None,
                slice_spacing_hint=thick[0][0] if thick else None,
                origin_hint=g.get("top_pos"),
            )
            warnings.extend(plan.notes)
            if g["modality"] != "CT":
                warnings.append(f"Modalität „{g['modality'] or 'leer'}“ wird auf CT gesetzt")
            if key[0] == "MF":
                warnings.append("Multiframe-Datei wird in Einzelschichten zerlegt")
            if compressed:
                warnings.append("Komprimierte Bilddaten werden entpackt")
            if not g["has_series_uid"]:
                warnings.append("Kennungen (UIDs) fehlten und werden neu erzeugt")
        else:
            if g["samples"] != 1:
                warnings.append("Farbbild(er), kein DVT-Volumen")
            else:
                warnings.append("Zu wenige Schichten für ein DVT-Volumen")

        if not g["patient"].last_name:
            warnings.append("Kein Patientenname in den Daten")

        series_list.append(SeriesInfo(
            key="|".join(str(k) for k in key),
            kind=KIND_VOLUME if is_volume else KIND_IMAGES,
            patient=g["patient"],
            source_study_uid=g["study_uid"],
            modality=g["modality"],
            manufacturer=g["manufacturer"],
            model=g["model"],
            rows=g["rows"], columns=g["cols"],
            transfer_syntax=ts,
            is_compressed=compressed,
            slices=g["slices"],
            plan=plan,
            warnings=warnings,
            source_dir=g["dir"],
        ))

    # Volumen zuerst, größte zuerst.
    series_list.sort(key=lambda s: (s.kind != KIND_VOLUME, -s.num_output, s.key))
    return ScanResult(series=series_list, skipped_files=skipped, total_files_seen=total_seen)
