import numpy as np
import pydicom
import pytest
from PIL import Image
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from behandlungsplaner import storage
from behandlungsplaner.models import KIND_IMPLANTAT, PlanItem, TreatmentPlan


def _make_plain_image(path, size=(400, 200), color=(120, 120, 120)):
    Image.new("RGB", size, color).save(path)
    return path


def _make_dicom_opg(path, rows=300, cols=600):
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = pydicom.uid.SecondaryCaptureImageStorage
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.Modality = "PX"
    ds.Rows = rows
    ds.Columns = cols
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    # Gradient, damit Fensterung/Normalisierung ueberprueft werden kann.
    gradient = np.tile(np.linspace(0, 4000, cols, dtype=np.uint16), (rows, 1))
    ds.PixelData = gradient.tobytes()
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.save_as(str(path), enforce_file_format=True)
    return path


def test_import_plain_png(tmp_path):
    src = _make_plain_image(tmp_path / "opg_export.png")
    dest = tmp_path / "plan_folder"
    dest.mkdir()
    filename, w, h = storage.import_image(src, dest)
    assert filename == "opg.png"
    assert (dest / "opg.png").exists()
    assert (w, h) == (400, 200)


def test_import_dicom_opg(tmp_path):
    src = _make_dicom_opg(tmp_path / "OPG_EXPORT")  # keine Endung, wie oft bei DICOM-CDs
    dest = tmp_path / "plan_folder"
    dest.mkdir()
    filename, w, h = storage.import_image(src, dest)
    assert filename == "opg.png"
    assert (w, h) == (600, 300)
    img = Image.open(dest / "opg.png")
    arr = np.array(img.convert("L"))
    # Gradient sollte nach der Normalisierung noch von dunkel nach hell verlaufen.
    assert arr[:, 0].mean() < arr[:, -1].mean()


def test_sanitize_and_folder_name_handles_special_chars():
    name = storage.suggest_folder_name("Müller-Schmidt, Érika/Test", "2026-08-21")
    assert "/" not in name
    assert name.startswith("M")
    assert "2026-08-21" in name


def test_create_plan_folder_avoids_collisions(tmp_path):
    plan1 = TreatmentPlan(patient_name="Erika Mustermann", plan_date="2026-08-21")
    plan2 = TreatmentPlan(patient_name="Erika Mustermann", plan_date="2026-08-21")
    folder1 = storage.create_plan_folder(tmp_path, plan1)
    folder2 = storage.create_plan_folder(tmp_path, plan2)
    assert folder1 != folder2
    assert folder1.exists() and folder2.exists()


def test_save_and_load_plan_roundtrip(tmp_path):
    plan = TreatmentPlan(patient_name="Erika Mustermann", plan_date="2026-08-21", image_filename="opg.png")
    plan.add_item(PlanItem(kind=KIND_IMPLANTAT, x=0.3, y=0.4, width=0.05, height=0.08, fdi_tooth=36, cost=1800))
    folder = storage.create_plan_folder(tmp_path, plan)
    storage.save_plan(plan, folder)

    loaded = storage.load_plan(folder)
    assert loaded.patient_name == "Erika Mustermann"
    assert len(loaded.items) == 1
    assert loaded.items[0].fdi_tooth == 36


def test_list_plans_returns_sorted_summaries(tmp_path):
    plan_a = TreatmentPlan(patient_name="Anna A", plan_date="2026-08-01")
    plan_a.add_item(PlanItem(kind=KIND_IMPLANTAT, x=0.1, y=0.1, width=0.05, height=0.08, cost=100))
    folder_a = storage.create_plan_folder(tmp_path, plan_a)
    storage.save_plan(plan_a, folder_a)

    plan_b = TreatmentPlan(patient_name="Bernd B", plan_date="2026-08-10")
    folder_b = storage.create_plan_folder(tmp_path, plan_b)
    storage.save_plan(plan_b, folder_b)

    summaries = storage.list_plans(tmp_path)
    assert len(summaries) == 2
    names = {s.patient_name for s in summaries}
    assert names == {"Anna A", "Bernd B"}
    by_name = {s.patient_name: s for s in summaries}
    assert by_name["Anna A"].item_count == 1
    assert by_name["Anna A"].total_cost == 100


def test_list_plans_empty_root_returns_empty_list(tmp_path):
    assert storage.list_plans(tmp_path / "does_not_exist") == []


def test_duplicate_plan_copies_image_and_items(tmp_path):
    plan = TreatmentPlan(patient_name="Erika Mustermann", plan_date="2026-08-21")
    src_img = _make_plain_image(tmp_path / "src.png")
    folder = storage.create_plan_folder(tmp_path, plan)
    filename, w, h = storage.import_image(src_img, folder)
    plan.image_filename, plan.image_width_px, plan.image_height_px = filename, w, h
    plan.add_item(PlanItem(kind=KIND_IMPLANTAT, x=0.2, y=0.2, width=0.05, height=0.08, cost=1800))
    storage.save_plan(plan, folder)

    new_folder = storage.duplicate_plan(folder, tmp_path, new_plan_date="2026-09-01")
    assert new_folder != folder
    assert (new_folder / "opg.png").exists()

    duplicated = storage.load_plan(new_folder)
    assert duplicated.plan_date == "2026-09-01"
    assert duplicated.plan_id != TreatmentPlan.from_dict(
        __import__("json").loads((folder / "plan.json").read_text())
    ).plan_id
    assert len(duplicated.items) == 1


def test_delete_plan_removes_folder(tmp_path):
    plan = TreatmentPlan(patient_name="Loeschen Test")
    folder = storage.create_plan_folder(tmp_path, plan)
    storage.save_plan(plan, folder)
    assert folder.exists()
    storage.delete_plan(folder)
    assert not folder.exists()
