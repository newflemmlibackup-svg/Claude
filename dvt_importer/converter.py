"""Schreibt erkannte Serien als sauberes, Sidexis-taugliches DICOM-Medium.

Jede Schicht eines DVT-Volumens wird **komplett neu aufgebaut**: Aus der
Fremddatei werden nur die Bildpunkte und wenige geprüfte Angaben übernommen.
Das Ergebnis ist immer gleich aufgebaut - unabhängig davon, von welchem Gerät
die Daten stammen:

  * klassische Einzelschichten "CT Image Storage" (kein Multiframe)
  * unkomprimiert, Explicit VR Little Endian, 16 Bit Graustufen
  * lückenlose Nummerierung, exakt gleichmäßige Schichtabstände
  * neue, in sich stimmige UIDs und eine gültige DICOMDIR
  * fehlende oder unlesbare Schichten werden durch schwarze Schichten ersetzt
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.fileset import FileSet
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

from . import __version__
from .scanner import KIND_VOLUME, PatientData, SeriesInfo, UNCOMPRESSED_TRANSFER_SYNTAXES

IMPLEMENTATION_CLASS_UID = "1.2.826.0.1.3680043.8.498.77"  # pydicom-Wurzel + eigene Kennung
FLAT_SUFFIX = "_dcm-Einzeldateien"


@dataclass
class ConversionResult:
    output_dir: Path
    flat_dir: Optional[Path] = None
    series_converted: int = 0
    images_written: int = 0
    black_missing: int = 0        # im Datensatz fehlende Schichten
    black_damaged: int = 0        # vorhandene, aber unlesbare Schichten
    partially_damaged: int = 0    # abgeschnittene Schichten, Rest schwarz
    verified: bool = False
    per_series_log: list = field(default_factory=list)
    problems: list = field(default_factory=list)


class ConversionError(Exception):
    pass


# ---------------------------------------------------------------- Pixel lesen
class _FrameLoader:
    """Liest einzelne Schichten als 2D-Array mit den gespeicherten Rohwerten."""

    def __init__(self):
        self._path = None
        self._ds = None
        self._frames = None

    def _open(self, path: Path):
        if self._path != path:
            self._ds = pydicom.dcmread(str(path), force=True)
            self._frames = None
            self._path = path
        return self._ds

    def load(self, ref) -> tuple:
        """Liefert (array, header, abgeschnitten?)."""
        ds = self._open(ref.path)
        if "PixelData" not in ds:
            raise ValueError("keine Bilddaten enthalten")
        rows, cols = int(ds.Rows), int(ds.Columns)
        bits = int(ds.get("BitsAllocated", 16))
        if int(ds.get("SamplesPerPixel", 1)) != 1:
            raise ValueError("kein Graustufenbild")
        if bits not in (8, 16, 32):
            raise ValueError(f"nicht unterstützte Bittiefe ({bits})")
        signed = int(ds.get("PixelRepresentation", 0)) == 1
        frames = int(ds.get("NumberOfFrames", 1) or 1)
        index = ref.frame or 0

        ts = ""
        try:
            ts = str(ds.file_meta.get("TransferSyntaxUID", "") or "")
        except Exception:  # noqa: BLE001
            pass

        truncated = False
        if not ts or ts in UNCOMPRESSED_TRANSFER_SYNTAXES:
            dtype = np.dtype(f"{'>' if ts == '1.2.840.10008.1.2.2' else '<'}{'i' if signed else 'u'}{bits // 8}")
            raw = ds.PixelData
            n = rows * cols
            start = index * n * dtype.itemsize
            chunk = raw[start:start + n * dtype.itemsize]
            usable = len(chunk) // dtype.itemsize
            if usable == 0:
                raise ValueError("Bilddaten leer oder abgeschnitten")
            arr = np.frombuffer(chunk, dtype=dtype, count=usable)
            if usable < n:
                truncated = True
                full = np.zeros(n, dtype=dtype)
                full[:usable] = arr
                mask = np.zeros(n, dtype=bool)
                mask[usable:] = True
                arr = np.ma.array(full, mask=mask)
            arr = arr.reshape(rows, cols)
        else:
            if "TransferSyntaxUID" not in getattr(ds, "file_meta", {}):
                raise ValueError("unbekannte Kodierung")
            if self._frames is None:
                self._frames = ds.pixel_array
            arr = self._frames[index] if frames > 1 else self._frames
            if arr.shape != (rows, cols):
                raise ValueError("unerwartete Bildgröße nach dem Entpacken")
        return arr, ds, truncated


def _clean_values(arr, ds):
    """Unbenutzte Bits entfernen, MONOCHROME1 umkehren -> echte Rohwerte als int64."""
    bits_alloc = int(ds.get("BitsAllocated", 16))
    bits_stored = int(ds.get("BitsStored", bits_alloc) or bits_alloc)
    signed = int(ds.get("PixelRepresentation", 0)) == 1
    mask = np.ma.getmaskarray(arr) if isinstance(arr, np.ma.MaskedArray) else None
    data = np.asarray(np.ma.getdata(arr)).astype(np.int64)
    if 0 < bits_stored < bits_alloc:
        if signed:
            shift = 64 - bits_stored
            data = (data << shift) >> shift
        else:
            data &= (1 << bits_stored) - 1
    if str(ds.get("PhotometricInterpretation", "")).strip() == "MONOCHROME1":
        lo, hi = (-(1 << (bits_stored - 1)), (1 << (bits_stored - 1)) - 1) if signed else (0, (1 << bits_stored) - 1)
        data = hi + lo - data
    return data, mask


def _rescale(ds) -> tuple:
    try:
        slope = float(ds.get("RescaleSlope", 1) or 1)
        intercept = float(ds.get("RescaleIntercept", 0) or 0)
    except (TypeError, ValueError):
        slope, intercept = 1.0, 0.0
    return (slope if slope != 0 else 1.0), intercept


# ------------------------------------------------------------ Metadaten bauen
def _pn(patient: PatientData) -> str:
    last = patient.last_name.strip() or "Unbekannt"
    first = patient.first_name.strip()
    return f"{last}^{first}" if first else last


def _charset(*texts) -> str:
    try:
        "".join(texts).encode("latin-1")
        return "ISO_IR 100"
    except UnicodeEncodeError:
        return "ISO_IR 192"


def _apply_common(ds: Dataset, patient: PatientData, study: dict, source_hdr) -> None:
    ds.SpecificCharacterSet = _charset(patient.last_name, patient.first_name, patient.description,
                                       patient.patient_id)
    ds.PatientName = _pn(patient)
    ds.PatientID = patient.patient_id.strip() or "UNBEKANNT"
    ds.PatientBirthDate = patient.birth_date
    ds.PatientSex = patient.sex
    ds.StudyInstanceUID = study["uid"]
    ds.StudyID = study["id"]
    ds.StudyDate = study["date"]
    ds.StudyTime = study["time"]
    ds.SeriesDate = study["date"]
    ds.SeriesTime = study["time"]
    ds.ContentDate = study["date"]
    ds.ContentTime = study["time"]
    ds.AcquisitionDate = study["date"]
    ds.AcquisitionTime = study["time"]
    ds.AccessionNumber = ""
    ds.ReferringPhysicianName = ""
    desc = (patient.description.strip() or "DVT")[:64]
    ds.StudyDescription = desc
    ds.SeriesDescription = desc
    for tag in ("Manufacturer", "ManufacturerModelName", "InstitutionName"):
        val = str(source_hdr.get(tag, "") or "").strip() if source_hdr is not None else ""
        if tag == "Manufacturer" or val:
            setattr(ds, tag, val[:64])


def _file_meta(sop_class, sop_uid) -> FileMetaDataset:
    meta = FileMetaDataset()
    meta.FileMetaInformationVersion = b"\x00\x01"
    meta.MediaStorageSOPClassUID = sop_class
    meta.MediaStorageSOPInstanceUID = sop_uid
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.ImplementationClassUID = IMPLEMENTATION_CLASS_UID
    meta.ImplementationVersionName = f"DVTIMPORT_{__version__}"[:16]
    return meta


def _ds_num(value: float) -> str:
    """Dezimalzahl als DICOM-DS (max. 16 Zeichen)."""
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


# ---------------------------------------------------------- Volumen schreiben
def _convert_volume(series: SeriesInfo, study: dict, series_number: int, emit, log, tick,
                    result: ConversionResult) -> None:
    plan = series.plan
    loader = _FrameLoader()
    rows, cols = series.rows, series.columns
    real = [s for s in plan.slots if s is not None]

    # Referenz-Header und Schwarzwert aus einigen Stichproben bestimmen.
    ref_hdr = None
    sample_min = None
    step = max(1, len(real) // 6)
    candidates = real[::step] + [real[-1]]
    for attempt, ref in enumerate(candidates + real):
        if attempt >= len(candidates) and ref_hdr is not None:
            break
        try:
            arr, hdr, _ = loader.load(ref)
            data, mask = _clean_values(arr, hdr)
        except Exception:  # noqa: BLE001
            continue
        if ref_hdr is None:
            ref_hdr = hdr
        if mask is not None:
            data = data[~mask]
        cur = int(data.min())
        sample_min = cur if sample_min is None else min(sample_min, cur)
    if ref_hdr is None:
        raise ConversionError("Keine einzige Schicht dieser Serie ist lesbar")

    signed = int(ref_hdr.get("PixelRepresentation", 0)) == 1 or sample_min < 0
    out_dtype = np.int16 if signed else np.uint16
    info = np.iinfo(out_dtype)
    ref_slope, ref_intercept = _rescale(ref_hdr)
    black = int(min(max(sample_min, info.min), info.max))

    series_uid = generate_uid()
    frame_uid = generate_uid()
    n_missing = n_damaged = n_partial = 0

    for index, ref in enumerate(plan.slots):
        pixels = None
        if ref is None:
            n_missing += 1
        else:
            try:
                arr, hdr, truncated = loader.load(ref)
                if arr.shape != (rows, cols):
                    raise ValueError("abweichende Bildgröße")
                data, mask = _clean_values(arr, hdr)
                slope, intercept = _rescale(hdr)
                if (slope, intercept) != (ref_slope, ref_intercept):
                    data = np.rint((data * slope + intercept - ref_intercept) / ref_slope).astype(np.int64)
                if mask is not None:
                    data[mask] = black
                if truncated:
                    n_partial += 1
                    log(f"  Schicht {index + 1}: Datei {ref.path.name} ist abgeschnitten – Rest schwarz aufgefüllt")
                pixels = np.clip(data, info.min, info.max).astype(out_dtype)
            except Exception as exc:  # noqa: BLE001
                n_damaged += 1
                log(f"  Schicht {index + 1}: {ref.path.name} unlesbar ({exc}) – durch schwarze Schicht ersetzt")
        if pixels is None:
            pixels = np.full((rows, cols), black, dtype=out_dtype)

        sop_uid = generate_uid()
        ds = Dataset()
        ds.file_meta = _file_meta(CTImageStorage, sop_uid)
        _apply_common(ds, series.patient, study, ref_hdr)
        ds.ImageType = ["ORIGINAL", "PRIMARY", "AXIAL"]
        ds.SOPClassUID = CTImageStorage
        ds.SOPInstanceUID = sop_uid
        ds.Modality = "CT"
        ds.SeriesInstanceUID = series_uid
        ds.SeriesNumber = series_number
        ds.AcquisitionNumber = 1
        ds.InstanceNumber = index + 1
        ds.PatientPosition = "HFS"
        ds.FrameOfReferenceUID = frame_uid
        ds.PositionReferenceIndicator = ""
        pos = plan.position_of(index)
        ds.ImagePositionPatient = [_ds_num(v) for v in pos]
        ds.ImageOrientationPatient = [_ds_num(v) for v in plan.iop]
        ds.SliceLocation = _ds_num(index * plan.slice_spacing)
        ds.SliceThickness = _ds_num(plan.slice_spacing)
        ds.SpacingBetweenSlices = _ds_num(plan.slice_spacing)
        ds.PixelSpacing = [_ds_num(v) for v in plan.pixel_spacing]
        kvp = ref_hdr.get("KVP")
        ds.KVP = kvp if kvp not in (None, "") else None
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.Rows = rows
        ds.Columns = cols
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 1 if signed else 0
        ds.RescaleIntercept = _ds_num(ref_intercept)
        ds.RescaleSlope = _ds_num(ref_slope)
        for tag in ("WindowCenter", "WindowWidth"):
            try:
                val = ref_hdr.get(tag)
                val = val[0] if isinstance(val, (list, pydicom.multival.MultiValue)) else val
                if val not in (None, ""):
                    setattr(ds, tag, _ds_num(float(val)))
            except (TypeError, ValueError):
                pass
        ds.PixelData = pixels.astype(pixels.dtype.newbyteorder("<")).tobytes()
        emit(ds, series_number, index + 1)
        tick()

    result.black_missing += n_missing
    result.black_damaged += n_damaged
    result.partially_damaged += n_partial
    line = f"{series.patient.display_name}: {len(plan.slots)} Schichten geschrieben"
    extras = []
    if n_missing:
        extras.append(f"{n_missing} fehlende schwarz ergänzt")
    if n_damaged:
        extras.append(f"{n_damaged} unlesbare schwarz ersetzt")
    if n_partial:
        extras.append(f"{n_partial} abgeschnittene teilweise aufgefüllt")
    result.per_series_log.append(line + (f" ({', '.join(extras)})" if extras else ""))
    if not plan.spacing_known:
        result.problems.append("Voxelgröße war in den Fremddaten nicht angegeben – Längenmessungen "
                               "in diesem Volumen sind nicht verlässlich.")


# ------------------------------------------------------ Einzelbilder schreiben
def _convert_images(series: SeriesInfo, study: dict, series_number: int, emit, log, tick,
                    result: ConversionResult) -> None:
    """Einzelbilder (z. B. Übersichten) bleiben inhaltlich erhalten, werden nur bereinigt."""
    series_uid = generate_uid()
    written = 0
    for number, ref in enumerate(series.slices, start=1):
        tick()
        try:
            ds = pydicom.dcmread(str(ref.path), force=True)
            ts = str(getattr(ds, "file_meta", {}).get("TransferSyntaxUID", "") or "")
            if ts and ts not in UNCOMPRESSED_TRANSFER_SYNTAXES:
                ds.decompress()
            elif ts in ("", "1.2.840.10008.1.2", "1.2.840.10008.1.2.2"):
                # Auf Explicit VR Little Endian umkodieren (Pflicht für DICOM-Medien).
                if ts == "1.2.840.10008.1.2.2" and int(ds.get("BitsAllocated", 8)) > 8:
                    width = int(ds.BitsAllocated) // 8
                    ds.PixelData = np.frombuffer(ds.PixelData, dtype=f">u{width}").astype(f"<u{width}").tobytes()
            if "PixelData" not in ds:
                raise ValueError("keine Bilddaten enthalten")
        except Exception as exc:  # noqa: BLE001
            log(f"  {ref.path.name} unlesbar ({exc}) – übersprungen")
            result.problems.append(f"Einzelbild {ref.path.name} konnte nicht übernommen werden.")
            continue
        ds.remove_private_tags()
        sop_class = ds.get("SOPClassUID") or pydicom.uid.SecondaryCaptureImageStorage
        sop_uid = generate_uid()
        hdr = ds
        _apply_common(ds, series.patient, study, hdr)
        ds.SOPClassUID = sop_class
        ds.SOPInstanceUID = sop_uid
        if not str(ds.get("Modality", "")).strip():
            ds.Modality = "OT"
        ds.SeriesInstanceUID = series_uid
        ds.SeriesNumber = series_number
        ds.InstanceNumber = number
        ds.file_meta = _file_meta(sop_class, sop_uid)
        emit(ds, series_number, number)
        written += 1
    result.per_series_log.append(f"{series.patient.display_name}: {written} Einzelbild(er) übernommen")


# ------------------------------------------------------------------ Hauptablauf
def validate_patient(patient: PatientData) -> list:
    errors = []
    for label, value in (("Geburtsdatum", patient.birth_date), ("Aufnahmedatum", patient.study_date)):
        if value:
            try:
                _dt.datetime.strptime(value, "%Y%m%d")
            except ValueError:
                errors.append(f"{label} ist kein gültiges Datum")
    if patient.sex not in ("", "M", "F", "O"):
        errors.append("Geschlecht muss M, F oder O sein")
    return errors


def convert_series_list(
    series_list,
    output_dir,
    log: Optional[Callable[[str], None]] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    write_flat_copy: bool = False,
) -> ConversionResult:
    """Schreibt die Serien als DICOM-Medium mit DICOMDIR nach `output_dir`.

    Mit `write_flat_copy` entsteht daneben zusätzlich ein Ordner mit einfachen
    `.dcm`-Einzeldateien (für Programme, die keine DICOMDIR lesen).
    """
    log = log or (lambda msg: None)
    output_dir = Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ConversionError(f"Der Zielordner ist nicht leer: {output_dir}")
    for series in series_list:
        errors = validate_patient(series.patient)
        if errors:
            raise ConversionError(f"{series.patient.display_name}: " + "; ".join(errors))
    output_dir.mkdir(parents=True, exist_ok=True)

    result = ConversionResult(output_dir=output_dir)
    flat_dir = None
    if write_flat_copy:
        flat_dir = output_dir.parent / (output_dir.name + FLAT_SUFFIX)
        flat_dir.mkdir(parents=True, exist_ok=True)
        result.flat_dir = flat_dir

    total = sum(s.num_output for s in series_list)
    done = [0]

    def tick():
        done[0] += 1
        if progress_cb:
            progress_cb(done[0], total)

    fset = FileSet()
    fset.ID = "DVT_IMPORT"
    written = [0]

    def emit(ds, series_number, instance_number):
        if flat_dir is not None:
            ds.save_as(str(flat_dir / f"S{series_number:02d}_{instance_number:04d}.dcm"),
                       enforce_file_format=True)
        fset.add(ds)
        written[0] += 1

    now = _dt.datetime.now()
    studies: dict = {}
    for number, series in enumerate(series_list, start=1):
        p = series.patient
        study_key = (series.source_study_uid or series.key, p.last_name, p.first_name, p.birth_date,
                     p.patient_id, p.study_date)
        study = studies.get(study_key)
        if study is None:
            study = studies[study_key] = {
                "uid": generate_uid(),
                "id": str(len(studies) + 1),
                "date": p.study_date or now.strftime("%Y%m%d"),
                "time": "120000",
            }
        log(f"Verarbeite: {series.display_label}")
        try:
            if series.kind == KIND_VOLUME:
                _convert_volume(series, study, number, emit, log, tick, result)
            else:
                _convert_images(series, study, number, emit, log, tick, result)
            result.series_converted += 1
        except ConversionError as exc:
            log(f"  FEHLER: {exc}")
            result.problems.append(f"{series.display_label}: {exc}")

    if written[0] == 0:
        raise ConversionError("Es konnte kein einziges Bild geschrieben werden.")

    log("Schreibe DICOMDIR …")
    fset.write(output_dir)
    result.images_written = written[0]

    log("Prüfe das Ergebnis …")
    result.verified = verify_output(output_dir, written[0], result.problems)
    log("Fertig." if result.verified else "Fertig – die Abschlussprüfung hat Auffälligkeiten gemeldet.")
    return result


def verify_output(output_dir: Path, expected_images: int, problems: list) -> bool:
    """Liest das geschriebene Medium zurück und prüft Vollständigkeit und Konsistenz."""
    try:
        fs = FileSet(str(Path(output_dir) / "DICOMDIR"))
        count = 0
        per_series: dict = {}
        for inst in fs:
            path = Path(inst.path)
            ds = pydicom.dcmread(str(path), stop_before_pixels=True)
            expected = int(ds.Rows) * int(ds.Columns) * int(ds.get("SamplesPerPixel", 1)) \
                * int(ds.BitsAllocated) // 8 * int(ds.get("NumberOfFrames", 1) or 1)
            if ds.Modality == "CT" and path.stat().st_size < expected:
                raise ValueError(f"{path.name} ist unvollständig")
            per_series.setdefault(ds.SeriesInstanceUID, []).append(int(ds.InstanceNumber))
            count += 1
        if count != expected_images:
            raise ValueError(f"{count} statt {expected_images} Bilder im Medium")
        for numbers in per_series.values():
            if sorted(numbers) != list(range(1, len(numbers) + 1)):
                raise ValueError("Bildnummern nicht lückenlos")
        return True
    except Exception as exc:  # noqa: BLE001
        problems.append(f"Abschlussprüfung fehlgeschlagen: {exc}")
        return False
