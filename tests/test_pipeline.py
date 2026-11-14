"""End-to-End-Tests mit synthetischen, absichtlich "kaputten" Fremd-DVT-Daten."""
from pathlib import Path

import numpy as np
import pydicom
import pytest
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.filewriter import dcmwrite
from pydicom.fileset import FileSet
from pydicom.uid import (CTImageStorage, EnhancedCTImageStorage, ExplicitVRLittleEndian,
                         RLELossless, generate_uid)

from dvt_importer.converter import ConversionError, convert_series_list
from dvt_importer.scanner import KIND_IMAGES, KIND_VOLUME, scan_source

SIZE = 32


def _pixels(i: int) -> np.ndarray:
    arr = np.full((SIZE, SIZE), -1000, dtype=np.int16)
    arr[8:24, 8:24] = 100 + i
    return arr


def _base_slice(i: int, patient_id: str = "P100", z_step: float = 0.25) -> Dataset:
    ds = Dataset()
    ds.PatientID = patient_id
    ds.PatientName = "Mustermann^Erika"
    ds.PatientBirthDate = "19700315"
    ds.Rows = SIZE
    ds.Columns = SIZE
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 1
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.InstanceNumber = i
    ds.ImagePositionPatient = [-10.0, -10.0, i * z_step]
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.PixelSpacing = [0.25, 0.25]
    ds.SliceThickness = 0.25
    ds.PixelData = _pixels(i).tobytes()
    return ds


def _write_raw(path: Path, ds: Dataset):
    """Ohne Präambel und File-Meta schreiben, wie manche Geräte es tun."""
    dcmwrite(str(path), ds, implicit_vr=True, little_endian=True, enforce_file_format=False)


def make_export(root: Path, numbers, with_uids=False, **kw) -> Path:
    out = root / "FREMD_DVT" / "SCAN1"
    out.mkdir(parents=True, exist_ok=True)
    study, series = generate_uid(), generate_uid()
    for i in numbers:
        ds = _base_slice(i, **kw)
        if with_uids:
            ds.StudyInstanceUID, ds.SeriesInstanceUID = study, series
            ds.SOPInstanceUID, ds.SOPClassUID = generate_uid(), CTImageStorage
            ds.Modality = "OT"
        _write_raw(out / f"IMG{i:04d}", ds)
    return out


def make_broken_no_uid_export(root: Path, num_slices: int = 8) -> Path:
    return make_export(root, range(1, num_slices + 1))


def _read_volume(out_dir: Path):
    fs = FileSet(str(out_dir / "DICOMDIR"))
    slices = sorted((pydicom.dcmread(i.path) for i in fs), key=lambda d: int(d.InstanceNumber))
    return fs, slices


def test_clean_rebuild_without_uids(tmp_path):
    make_broken_no_uid_export(tmp_path / "usb", 8)
    scan = scan_source(tmp_path / "usb")
    assert scan.skipped_files == 0 and len(scan.series) == 1
    series = scan.series[0]
    assert series.kind == KIND_VOLUME and series.num_missing == 0
    assert series.patient.last_name == "Mustermann" and series.patient.first_name == "Erika"

    result = convert_series_list([series], tmp_path / "out")
    assert result.verified and result.images_written == 8 and not result.problems

    _, slices = _read_volume(tmp_path / "out")
    assert len(slices) == 8
    assert len({d.SeriesInstanceUID for d in slices}) == 1
    assert len({d.SOPInstanceUID for d in slices}) == 8
    for i, d in enumerate(slices, start=1):
        assert d.Modality == "CT" and d.SOPClassUID == CTImageStorage
        assert d.file_meta.TransferSyntaxUID == ExplicitVRLittleEndian
        assert d.BitsAllocated == 16 and d.PhotometricInterpretation == "MONOCHROME2"
        assert [float(v) for v in d.ImagePositionPatient] == pytest.approx([-10, -10, i * 0.25])
        assert np.array_equal(d.pixel_array, _pixels(i))


def test_missing_slices_are_filled_black(tmp_path):
    # Schichten 4, 5 und 9 fehlen im Datensatz.
    present = [1, 2, 3, 6, 7, 8, 10, 11, 12]
    make_export(tmp_path / "usb", present, with_uids=True)
    series = scan_source(tmp_path / "usb").series[0]
    assert series.num_missing == 3 and series.num_output == 12
    assert any("fehlende" in w for w in series.warnings)

    result = convert_series_list([series], tmp_path / "out")
    assert result.black_missing == 3 and result.verified

    _, slices = _read_volume(tmp_path / "out")
    assert [int(d.InstanceNumber) for d in slices] == list(range(1, 13))
    z = [float(d.ImagePositionPatient[2]) for d in slices]
    assert np.allclose(np.diff(z), 0.25)
    for i, d in enumerate(slices, start=1):
        if i in present:
            assert np.array_equal(d.pixel_array, _pixels(i))
        else:
            assert (d.pixel_array == -1000).all()   # "schwarz" = dunkelster Wert (Luft)


def test_missing_detected_by_instance_number_without_positions(tmp_path):
    out = tmp_path / "usb" / "S"
    out.mkdir(parents=True)
    for i in (1, 2, 3, 5, 6):
        ds = _base_slice(i)
        del ds.ImagePositionPatient
        _write_raw(out / f"f{i}", ds)
    series = scan_source(tmp_path / "usb").series[0]
    assert series.num_missing == 1
    convert_series_list([series], tmp_path / "out")
    _, slices = _read_volume(tmp_path / "out")
    assert len(slices) == 6 and (slices[3].pixel_array == -1000).all()


def test_damaged_and_truncated_files(tmp_path):
    out = make_export(tmp_path / "usb", range(1, 11), with_uids=True)
    # Schicht 4: Bilddaten zur Hälfte abgeschnitten. Schicht 7: Bilddaten fehlen ganz.
    p4 = out / "IMG0004"
    p4.write_bytes(p4.read_bytes()[: p4.stat().st_size - SIZE * SIZE])
    ds7 = pydicom.dcmread(out / "IMG0007", force=True)
    del ds7.PixelData
    _write_raw(out / "IMG0007", ds7)
    # Schicht 9: Datei ist nur noch Datenmüll -> wird als Lücke erkannt.
    (out / "IMG0009").write_bytes(b"\xff" * 500)

    logs = []
    series = scan_source(tmp_path / "usb").series[0]
    assert series.num_missing == 1
    result = convert_series_list([series], tmp_path / "out", log=logs.append)
    assert (result.black_missing, result.black_damaged, result.partially_damaged) == (1, 1, 1)
    assert result.verified

    _, slices = _read_volume(tmp_path / "out")
    assert len(slices) == 10
    half = slices[3].pixel_array
    assert np.array_equal(half[: SIZE // 2], _pixels(4)[: SIZE // 2]) and (half[SIZE // 2:] == -1000).all()
    assert (slices[6].pixel_array == -1000).all() and (slices[8].pixel_array == -1000).all()


def test_patient_data_can_be_overridden(tmp_path):
    make_broken_no_uid_export(tmp_path / "usb", 6)
    series = scan_source(tmp_path / "usb").series[0]
    p = series.patient
    p.last_name, p.first_name = "Müller", "Jörg"
    p.birth_date, p.sex, p.patient_id = "19851224", "M", "4711"
    p.study_date, p.description = "20240102", "DVT Fremdpraxis"
    convert_series_list([series], tmp_path / "out")
    fs, slices = _read_volume(tmp_path / "out")
    for d in slices:
        assert str(d.PatientName) == "Müller^Jörg" and d.PatientID == "4711"
        assert d.PatientBirthDate == "19851224" and d.PatientSex == "M"
        assert d.StudyDate == "20240102" and d.SeriesDescription == "DVT Fremdpraxis"
    assert fs.find_values("PatientID") == ["4711"]

    p.birth_date = "19851340"
    with pytest.raises(ConversionError):
        convert_series_list([series], tmp_path / "out2")


def test_reversed_order_and_unsorted_names(tmp_path):
    out = tmp_path / "usb" / "S"
    out.mkdir(parents=True)
    # Bildnummer 1 liegt oben (höchstes z), Dateinamen sind zufällig.
    for n, i in enumerate([5, 2, 8, 1, 7, 3, 6, 4]):
        ds = _base_slice(i)
        ds.ImagePositionPatient = [0, 0, 10 - i * 0.25]
        _write_raw(out / f"x{n}.bin", ds)
    series = scan_source(tmp_path / "usb").series[0]
    convert_series_list([series], tmp_path / "out")
    _, slices = _read_volume(tmp_path / "out")
    for i, d in enumerate(slices, start=1):
        assert np.array_equal(d.pixel_array, _pixels(i))
        assert float(d.ImagePositionPatient[2]) == pytest.approx(10 - i * 0.25)


def _multiframe(path: Path, n: int, transfer_syntax=ExplicitVRLittleEndian):
    ds = _base_slice(1)
    del ds.ImagePositionPatient, ds.ImageOrientationPatient, ds.PixelSpacing, ds.InstanceNumber
    ds.SOPClassUID, ds.SOPInstanceUID = EnhancedCTImageStorage, generate_uid()
    ds.StudyInstanceUID, ds.SeriesInstanceUID = generate_uid(), generate_uid()
    ds.Modality = "CT"
    ds.NumberOfFrames = n
    shared = Dataset()
    pm = Dataset()
    pm.PixelSpacing, pm.SliceThickness = [0.2, 0.2], 0.2
    po = Dataset()
    po.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    shared.PixelMeasuresSequence, shared.PlaneOrientationSequence = [pm], [po]
    ds.SharedFunctionalGroupsSequence = [shared]
    per = []
    for f in range(n):
        item, pp = Dataset(), Dataset()
        pp.ImagePositionPatient = [0, 0, f * 0.2]
        item.PlanePositionSequence = [pp]
        per.append(item)
    ds.PerFrameFunctionalGroupsSequence = per
    volume = np.stack([_pixels(f + 1) for f in range(n)])
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.PixelData = volume.tobytes()
    if transfer_syntax != ExplicitVRLittleEndian:
        ds.compress(transfer_syntax, volume, generate_instance_uid=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(str(path), enforce_file_format=True)


@pytest.mark.parametrize("ts", [ExplicitVRLittleEndian, RLELossless])
def test_multiframe_is_split_into_single_slices(tmp_path, ts):
    _multiframe(tmp_path / "usb" / "volume.dcm", 9, ts)
    series = scan_source(tmp_path / "usb").series[0]
    assert series.kind == KIND_VOLUME and series.num_output == 9
    result = convert_series_list([series], tmp_path / "out")
    assert result.verified
    _, slices = _read_volume(tmp_path / "out")
    assert len(slices) == 9
    for f, d in enumerate(slices):
        assert d.SOPClassUID == CTImageStorage and "NumberOfFrames" not in d
        assert [float(v) for v in d.PixelSpacing] == [0.2, 0.2]
        assert float(d.ImagePositionPatient[2]) == pytest.approx(f * 0.2)
        assert np.array_equal(d.pixel_array, _pixels(f + 1))


def test_unsigned_12bit_with_overlay_bits_and_8bit(tmp_path):
    out = tmp_path / "usb" / "S"
    out.mkdir(parents=True)
    for i in range(1, 7):
        ds = _base_slice(i)
        ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 12, 11, 0
        arr = np.full((SIZE, SIZE), 500 + i, dtype=np.uint16) | 0x8000   # Müll in den oberen Bits
        ds.PixelData = arr.tobytes()
        _write_raw(out / f"a{i}", ds)
    series = scan_source(tmp_path / "usb").series[0]
    convert_series_list([series], tmp_path / "out")
    _, slices = _read_volume(tmp_path / "out")
    assert slices[0].PixelRepresentation == 0
    assert (slices[2].pixel_array == 503).all()


def test_non_dicom_files_and_single_images_are_separated(tmp_path):
    make_broken_no_uid_export(tmp_path / "usb", 6)
    (tmp_path / "usb" / "Viewer.exe").write_bytes(b"MZ" + b"\x00" * 5000)
    (tmp_path / "usb" / "liesmich.txt").write_text("Hallo")
    scout = _base_slice(1)
    scout.Rows = scout.Columns = 16
    scout.PixelData = np.zeros((16, 16), dtype=np.int16).tobytes()
    _write_raw(tmp_path / "usb" / "FREMD_DVT" / "SCAN1" / "SCOUT", scout)

    scan = scan_source(tmp_path / "usb")
    assert scan.skipped_files == 2
    assert [s.kind for s in scan.series] == [KIND_VOLUME, KIND_IMAGES]
    result = convert_series_list(scan.series, tmp_path / "out", write_flat_copy=True)
    assert result.images_written == 7 and result.verified
    assert len(list(result.flat_dir.glob("*.dcm"))) == 7


def test_refuses_non_empty_target(tmp_path):
    make_broken_no_uid_export(tmp_path / "usb", 6)
    series = scan_source(tmp_path / "usb").series
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "alt.txt").write_text("x")
    with pytest.raises(ConversionError):
        convert_series_list(series, tmp_path / "out")
