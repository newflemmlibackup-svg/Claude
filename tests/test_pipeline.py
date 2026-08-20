"""End-to-End-Test der Scan- und Konvertierungspipeline anhand synthetischer
'kaputter' Fremd-DVT-Daten, wie sie in der Praxis von fremden CBCT-Geraeten
exportiert werden (fehlende UIDs, kein DICOMDIR, falsches Modality-Tag,
keine Datei-Endung, kein Standard-Praeambel).
"""
from pathlib import Path

import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.encaps import encapsulate
from pydicom.filewriter import dcmwrite
from pydicom.fileset import FileSet
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from dvt_importer.converter import convert_series_list
from dvt_importer.scanner import scan_source


def _base_slice(instance_number: int, patient_id: str = "P100") -> Dataset:
    ds = Dataset()
    ds.PatientID = patient_id
    ds.PatientName = "Mustermann^Erika"
    ds.Rows = 32
    ds.Columns = 32
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 1
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.ImagePositionPatient = [0.0, 0.0, float(instance_number)]
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.PixelSpacing = [0.25, 0.25]
    ds.SliceThickness = 0.25
    arr = np.full((32, 32), instance_number, dtype=np.int16)
    ds.PixelData = arr.tobytes()
    ds.is_little_endian = True
    ds.is_implicit_VR = True
    return ds


def make_broken_no_uid_export(root: Path, num_slices: int = 8):
    """Simuliert einen einfachen CBCT-Export: kein DICOMDIR, keine UIDs,
    kein Modality-Tag, keine Dateiendung, kein Praeambel/File-Meta."""
    out = root / "FREMD_DVT" / "SCAN1"
    out.mkdir(parents=True)
    for i in range(1, num_slices + 1):
        ds = _base_slice(i)
        # Bewusst KEINE UIDs, KEIN Modality -> testet Fallback-Logik.
        path = out / f"IMG{i:04d}"  # keine Endung, wie bei manchen Geraeten
        dcmwrite(str(path), ds, write_like_original=True)
    return out


def make_export_with_uids_wrong_modality(root: Path, num_slices: int = 6):
    """Simuliert einen Export mit vorhandenen UIDs, aber falschem Modality-Tag
    ('OT' statt 'CT') und beliebiger Dateiendung."""
    out = root / "OTHER_UNIT" / "VOLUME"
    out.mkdir(parents=True)
    study_uid = generate_uid()
    series_uid = generate_uid()
    sop_uids = []
    for i in range(1, num_slices + 1):
        ds = _base_slice(i, patient_id="P200")
        ds.StudyInstanceUID = study_uid
        ds.SeriesInstanceUID = series_uid
        ds.SOPInstanceUID = generate_uid()
        ds.SOPClassUID = pydicom.uid.CTImageStorage
        ds.Modality = "OT"
        sop_uids.append(ds.SOPInstanceUID)
        path = out / f"slice_{i}.raw"
        dcmwrite(str(path), ds, write_like_original=True)
    return out, study_uid, series_uid, sop_uids


def test_scan_and_convert_broken_no_uid_export(tmp_path):
    source = tmp_path / "usb_stick"
    make_broken_no_uid_export(source, num_slices=8)

    result = scan_source(source)
    assert result.total_files_seen == 8
    assert result.skipped_files == 0
    assert len(result.series) == 1

    series = result.series[0]
    assert series.num_slices == 8
    assert series.study_uid is None
    assert series.series_uid is None
    assert any("Study-UID" in w for w in series.warnings)
    assert any("Modality" in w for w in series.warnings)

    out_dir = tmp_path / "sidexis_import"
    conv_result = convert_series_list([series], out_dir)

    assert conv_result.images_converted == 8
    dicomdir_path = out_dir / "DICOMDIR"
    assert dicomdir_path.exists()

    fs = FileSet(str(dicomdir_path))
    assert len(fs) == 8
    for instance in fs:
        assert instance.Modality == "CT"
        assert str(instance.PatientID) == "P100"
        assert instance.StudyInstanceUID
        assert instance.SeriesInstanceUID

    # Alle Instanzen muessen dieselbe Study-/Series-UID tragen (eine Serie).
    study_uids = {inst.StudyInstanceUID for inst in fs}
    series_uids = {inst.SeriesInstanceUID for inst in fs}
    assert len(study_uids) == 1
    assert len(series_uids) == 1

    # SOPInstanceUIDs muessen eindeutig sein.
    sop_uids = [inst.SOPInstanceUID for inst in fs]
    assert len(sop_uids) == len(set(sop_uids))


def test_scan_and_convert_preserves_existing_uids_fixes_modality(tmp_path):
    source = tmp_path / "usb_stick2"
    out, study_uid, series_uid, sop_uids = make_export_with_uids_wrong_modality(source, num_slices=6)

    result = scan_source(source)
    assert len(result.series) == 1
    series = result.series[0]
    assert series.study_uid == str(study_uid)
    assert series.series_uid == str(series_uid)
    assert any("Modality 'OT'" in w for w in series.warnings)

    out_dir = tmp_path / "sidexis_import2"
    convert_series_list([series], out_dir)

    fs = FileSet(str(out_dir / "DICOMDIR"))
    assert len(fs) == 6
    found_sops = set()
    for instance in fs:
        assert instance.Modality == "CT"  # korrigiert von 'OT'
        assert instance.StudyInstanceUID == study_uid
        assert instance.SeriesInstanceUID == series_uid
        found_sops.add(instance.SOPInstanceUID)
    # Urspruengliche SOPInstanceUIDs wurden beibehalten (nicht neu generiert).
    assert found_sops == set(sop_uids)


def test_two_series_different_patients_produce_separate_studies(tmp_path):
    source = tmp_path / "usb_stick3"
    make_broken_no_uid_export(source / "A", num_slices=4)
    out2 = source / "B" / "PAT2SCAN"
    out2.mkdir(parents=True)
    for i in range(1, 5):
        ds = _base_slice(i, patient_id="P999")
        dcmwrite(str(out2 / f"IMG{i:04d}"), ds, write_like_original=True)

    result = scan_source(source)
    assert len(result.series) == 2

    out_dir = tmp_path / "combined_import"
    convert_series_list(result.series, out_dir)

    fs = FileSet(str(out_dir / "DICOMDIR"))
    assert len(fs) == 8
    patient_ids = {inst.PatientID for inst in fs}
    assert patient_ids == {"P100", "P999"}


def test_decompression_failure_is_logged_but_does_not_abort(tmp_path, monkeypatch):
    source = tmp_path / "usb_stick4"
    out = source / "SERIES"
    out.mkdir(parents=True)

    for i in range(1, 4):
        file_meta = FileMetaDataset()
        file_meta.MediaStorageSOPClassUID = pydicom.uid.CTImageStorage
        file_meta.MediaStorageSOPInstanceUID = generate_uid()
        # Als "komprimiert" deklarieren, ohne echte Kompression -> decompress() soll fehlschlagen
        # und der Fehler abgefangen werden, ohne die gesamte Konvertierung abzubrechen.
        file_meta.TransferSyntaxUID = pydicom.uid.JPEG2000Lossless
        ds = FileDataset(None, {}, file_meta=file_meta, preamble=b"\x00" * 128)
        base = _base_slice(i)
        for elem in base:
            ds.add(elem)
        ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
        ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
        # Als encapsulated (kompatibel mit komprimierter Transfersyntax) markieren,
        # aber mit unbrauchbaren Fantasiedaten fuellen -> Dekodierung schlaegt fehl.
        ds.PixelData = encapsulate([b"\x00\x01garbage-not-real-jpeg2000-data"])
        ds["PixelData"].is_undefined_length = True
        ds.is_little_endian = True
        ds.is_implicit_VR = False
        dcmwrite(str(out / f"IMG{i:04d}"), ds, write_like_original=True)

    result = scan_source(source)
    assert len(result.series) == 1
    assert result.series[0].is_compressed

    logs = []
    out_dir = tmp_path / "out4"
    conv_result = convert_series_list(result.series, out_dir, log=logs.append)

    # Die Datei wird trotz fehlgeschlagener Dekompression mit den Originaldaten
    # in das Fileset uebernommen (kein Abbruch der gesamten Konvertierung).
    assert conv_result.images_converted == 3
    assert (out_dir / "DICOMDIR").exists()
    assert len(conv_result.decompression_failures) == 3
    assert any("Dekompression fehlgeschlagen" in msg for msg in logs)
