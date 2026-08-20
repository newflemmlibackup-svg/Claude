"""Normalisiert erkannte DICOM-Serien und schreibt sie als Sidexis-importierbares
DICOM-Fileset (mit gueltiger DICOMDIR) in einen Zielordner.

Sidexis importiert DICOM-Datensaetze ueber eine DICOMDIR-Datei am Wurzelverzeichnis
des gewaehlten Ordners/Mediums. Viele fremde DVT-Exporte liefern entweder keine
(gueltige) DICOMDIR, fehlende/inkonsistente UIDs, ein unpassendes Modality-Tag oder
komprimierte Bilddaten in einer Transfersyntax, die nicht unterstuetzt wird. Dieses
Modul behebt diese Punkte und baut das Fileset mit pydicom neu auf.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import pydicom
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

from .scanner import SeriesInfo, UNCOMPRESSED_TRANSFER_SYNTAXES

try:
    from pydicom.fileset import FileSet
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("pydicom >= 2.1 mit fileset-Unterstuetzung wird benoetigt") from exc


@dataclass
class ConversionResult:
    output_dir: Path
    series_converted: int
    images_converted: int
    decompression_failures: list = field(default_factory=list)
    per_series_log: list = field(default_factory=list)


def _fallback_date_time(ds) -> tuple:
    date = (
        ds.get("StudyDate")
        or ds.get("SeriesDate")
        or ds.get("AcquisitionDate")
        or ds.get("ContentDate")
        or "20000101"
    )
    time = (
        ds.get("StudyTime")
        or ds.get("SeriesTime")
        or ds.get("AcquisitionTime")
        or ds.get("ContentTime")
        or "000000"
    )
    return str(date)[:8] or "20000101", str(time)[:14] or "000000"


def _harmonize_instance(
    ds,
    *,
    study_uid: str,
    series_uid: str,
    study_id: str,
    series_number: str,
    instance_number: int,
    used_sop_uids: set,
    log: Callable[[str], None],
) -> None:
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid

    sop_uid = str(getattr(ds, "SOPInstanceUID", "") or "")
    if not sop_uid or sop_uid in used_sop_uids:
        sop_uid = generate_uid()
    used_sop_uids.add(sop_uid)
    ds.SOPInstanceUID = sop_uid

    if not getattr(ds, "SOPClassUID", None):
        ds.SOPClassUID = CTImageStorage

    if str(getattr(ds, "Modality", "")).strip() != "CT":
        ds.Modality = "CT"

    study_date, study_time = _fallback_date_time(ds)
    ds.StudyDate = getattr(ds, "StudyDate", None) or study_date
    ds.StudyTime = getattr(ds, "StudyTime", None) or study_time
    ds.StudyID = str(getattr(ds, "StudyID", "") or study_id)
    ds.SeriesNumber = getattr(ds, "SeriesNumber", None) or series_number
    ds.InstanceNumber = instance_number

    if not str(getattr(ds, "PatientID", "")).strip():
        ds.PatientID = "UNBEKANNT"
    if not str(getattr(ds, "PatientName", "")).strip():
        ds.PatientName = "Unbekannt^Fremdbehandler"

    # file_meta muss zur (ggf. nach Dekompression neuen) Transfersyntax passen.
    if not hasattr(ds, "file_meta") or ds.file_meta is None:
        ds.fix_meta_info(enforce_standard=False)
    ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    if "TransferSyntaxUID" not in ds.file_meta:
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian


def convert_series_list(
    series_list,
    output_dir,
    log: Optional[Callable[[str], None]] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> ConversionResult:
    """Konvertiert die uebergebenen Serien in ein gueltiges DICOM-Fileset.

    Parameters
    ----------
    series_list:
        Liste von `SeriesInfo`-Objekten (aus `scanner.scan_source`), die
        konvertiert werden sollen.
    output_dir:
        Zielordner. Wird angelegt, falls nicht vorhanden. Muss leer sein oder
        noch keine DICOMDIR enthalten.
    log:
        Optionaler Callback fuer Fortschritts-/Statusmeldungen (fuer die GUI).
    progress_cb:
        Optionaler Callback (aktuelle_datei_index, gesamt_dateien).
    """
    if log is None:
        log = lambda msg: None  # noqa: E731

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    total_images = sum(s.num_slices for s in series_list)
    done_images = 0
    decompression_failures = []
    per_series_log = []

    fset = FileSet()

    for study_counter, series in enumerate(series_list, start=1):
        study_uid = series.study_uid or generate_uid()
        series_uid = series.series_uid or generate_uid()
        study_id = str(study_counter)
        series_number = "1"
        used_sop_uids: set = set()

        log(f"Konvertiere Serie: {series.display_label}")
        images_ok = 0

        for instance_number, path in enumerate(series.file_paths, start=1):
            try:
                ds = pydicom.dcmread(str(path), force=True)
            except Exception as exc:  # noqa: BLE001
                log(f"  WARNUNG: {path.name} konnte nicht gelesen werden ({exc}) - uebersprungen")
                continue

            ts = None
            if hasattr(ds, "file_meta") and "TransferSyntaxUID" in ds.file_meta:
                ts = str(ds.file_meta.TransferSyntaxUID)

            if ts and ts not in UNCOMPRESSED_TRANSFER_SYNTAXES:
                try:
                    ds.decompress(generate_instance_uid=False)
                except Exception as exc:  # noqa: BLE001
                    msg = f"{path.name}: Dekompression fehlgeschlagen ({exc}) - Originaldaten werden uebernommen"
                    log(f"  WARNUNG: {msg}")
                    decompression_failures.append(msg)

            _harmonize_instance(
                ds,
                study_uid=study_uid,
                series_uid=series_uid,
                study_id=study_id,
                series_number=series_number,
                instance_number=instance_number,
                used_sop_uids=used_sop_uids,
                log=log,
            )

            fset.add(ds)
            images_ok += 1
            done_images += 1
            if progress_cb:
                progress_cb(done_images, total_images)

        per_series_log.append(f"{series.display_label}: {images_ok} Bild(er) konvertiert")

    log(f"Schreibe DICOMDIR und Bilddateien nach: {output_dir}")
    fset.write(output_dir)
    log("Fertig.")

    return ConversionResult(
        output_dir=output_dir,
        series_converted=len(series_list),
        images_converted=done_images,
        decompression_failures=decompression_failures,
        per_series_log=per_series_log,
    )
