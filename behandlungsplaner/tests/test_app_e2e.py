"""End-to-End-Test der Gesamtapplikation: Plan anlegen, alle 8 Symboltypen
platzieren, kalibrieren, Status/Kosten bearbeiten, Undo/Redo, Speichern,
PDF-Export, Startbildschirm-Navigation, Folgeplan duplizieren.

Modale native Dialoge (Datei-/Speicherdialoge, Eingabemasken) werden per
Monkeypatch umgangen, da sie sich nicht sinnvoll automatisiert bedienen
lassen - die dahinterliegende Anwendungslogik wird trotzdem vollstaendig
durchlaufen.
"""
import json
import os

import pytest
from PIL import Image

tk = pytest.importorskip("tkinter")

pytestmark = pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="Kein Display verfuegbar")


def _tk_available():
    try:
        root = tk.Tk()
        root.destroy()
        return True
    except tk.TclError:
        return False


class FakeEvent:
    def __init__(self, x, y):
        self.x = x
        self.y = y


@pytest.fixture()
def app_setup(tmp_path, monkeypatch):
    if not _tk_available():
        pytest.skip("Tk kann kein Fenster oeffnen")

    from behandlungsplaner import app as app_module

    data_root = tmp_path / "praxisdaten"
    monkeypatch.setattr(app_module.config_module, "load_config", lambda: {
        "data_root": str(data_root), "clinic_name": "Testpraxis",
    })
    monkeypatch.setattr(app_module.config_module, "save_config", lambda cfg: None)

    root = tk.Tk()
    application = app_module.BehandlungsplanerApp(root)
    root.update()
    yield root, application, tmp_path
    root.destroy()


def _make_source_image(tmp_path, name="src_opg.png", size=(1600, 800)):
    path = tmp_path / name
    Image.new("RGB", size, (110, 110, 110)).save(path)
    return path


def test_start_screen_shown_initially(app_setup):
    root, application, tmp_path = app_setup
    assert application.start_screen.winfo_ismapped()
    assert not application.editor_frame.winfo_ismapped()


def test_new_plan_flow_with_mocked_dialogs(app_setup, monkeypatch):
    from behandlungsplaner import app as app_module

    root, application, tmp_path = app_setup
    src_img = _make_source_image(tmp_path)

    monkeypatch.setattr(app_module.filedialog, "askopenfilename", lambda **kw: str(src_img))

    class FakeNewPlanDialog:
        def __init__(self, parent):
            self.result_values = {
                "patient_name": "Erika Mustermann",
                "patient_birthdate": "1980-05-01",
                "practitioner": "Dr. Beispiel",
                "plan_date": "2026-08-21",
            }

    monkeypatch.setattr(app_module, "NewPlanDialog", FakeNewPlanDialog)

    application.new_plan()
    root.update()

    assert application.plan is not None
    assert application.plan.patient_name == "Erika Mustermann"
    assert application.current_folder.exists()
    assert (application.current_folder / "opg.png").exists()
    assert (application.current_folder / "plan.json").exists()
    assert application.editor_frame.winfo_ismapped()
    assert not application.dirty


def _open_plan_directly(application, tmp_path):
    from behandlungsplaner import storage
    from behandlungsplaner.models import TreatmentPlan

    plan = TreatmentPlan(patient_name="Anna Test", practitioner="Dr. X", plan_date="2026-08-21")
    folder = storage.create_plan_folder(application.config["data_root"], plan)
    src_img = _make_source_image(tmp_path, name="anna.png")
    filename, w, h = storage.import_image(src_img, folder)
    plan.image_filename, plan.image_width_px, plan.image_height_px = filename, w, h
    storage.save_plan(plan, folder)
    application.open_plan_folder(folder)
    return folder


def test_place_all_symbol_kinds_and_list_updates(app_setup):
    from behandlungsplaner.models import ALL_KINDS, KIND_BRUECKE

    root, application, tmp_path = app_setup
    _open_plan_directly(application, tmp_path)
    root.update()

    canvas = application.canvas
    x, y = 300, 200
    for kind in ALL_KINDS:
        canvas._place_new_item(kind, x, y)
        x += 40
    root.update()

    assert len(application.plan.items) == len(ALL_KINDS)
    assert len(application.list_view.tree.get_children()) == len(ALL_KINDS)
    assert application.dirty is True

    bridge_items = [i for i in application.plan.items if i.kind == KIND_BRUECKE]
    assert len(bridge_items) == 1


def test_calibration_toggle_seeds_grid_and_enables_snap(app_setup):
    root, application, tmp_path = app_setup
    _open_plan_directly(application, tmp_path)
    root.update()

    assert application.plan.calibration_enabled is False
    application.calib_var.set(True)
    application._on_calibration_toggle()
    root.update()

    assert application.plan.calibration_enabled is True
    assert len(application.plan.calibration_points) == 32

    tooth = 24
    fx, fy = application.plan.calibration_points[tooth]
    cx, cy = application.canvas._frac_to_canvas(fx, fy)
    application.canvas._place_new_item("krone", cx, cy)
    root.update()

    placed = application.plan.items[-1]
    assert placed.fdi_tooth == tooth


def test_edit_item_via_list_view_and_undo_redo(app_setup):
    from behandlungsplaner.models import STATUS_DURCHGEFUEHRT, STATUS_GEPLANT

    root, application, tmp_path = app_setup
    _open_plan_directly(application, tmp_path)
    root.update()

    application.canvas._place_new_item("implantat", 300, 200)
    root.update()
    item = application.plan.items[0]
    assert len(application.plan.items) == 1

    item.cost = 1999.0
    item.mark_done()
    application._on_plan_changed()
    root.update()
    assert application.plan.items[0].status == STATUS_DURCHGEFUEHRT
    assert application.dirty is True

    application.canvas._place_new_item("krone", 500, 250)
    root.update()
    assert len(application.plan.items) == 2

    application.undo()
    root.update()
    assert len(application.plan.items) == 1

    application.undo()
    root.update()
    assert application.plan.items[0].status == STATUS_GEPLANT

    application.redo()
    root.update()
    assert application.plan.items[0].status == STATUS_DURCHGEFUEHRT

    application.redo()
    root.update()
    assert len(application.plan.items) == 2


def test_save_plan_persists_to_disk(app_setup):
    root, application, tmp_path = app_setup
    folder = _open_plan_directly(application, tmp_path)
    root.update()

    application.canvas._place_new_item("wurzelbehandlung", 300, 200)
    root.update()
    assert application.dirty is True

    application.save_plan()
    assert application.dirty is False

    with open(folder / "plan.json", "r", encoding="utf-8") as fh:
        data = json.load(fh)
    assert len(data["items"]) == 1
    assert data["items"][0]["kind"] == "wurzelbehandlung"


def test_export_pdf_with_mocked_save_dialog(app_setup, monkeypatch):
    from behandlungsplaner import app as app_module

    root, application, tmp_path = app_setup
    _open_plan_directly(application, tmp_path)
    root.update()
    application.canvas._place_new_item("krone", 300, 200)
    root.update()

    dest = tmp_path / "export.pdf"
    monkeypatch.setattr(app_module.filedialog, "asksaveasfilename", lambda **kw: str(dest))
    monkeypatch.setattr(app_module.messagebox, "showinfo", lambda *a, **kw: None)

    application._export_pdf()

    assert dest.exists()
    assert dest.stat().st_size > 1000


def test_back_to_start_and_duplicate_plan(app_setup):
    root, application, tmp_path = app_setup
    folder = _open_plan_directly(application, tmp_path)
    root.update()
    application.canvas._place_new_item("implantat", 300, 200)
    root.update()
    application.save_plan()

    application._back_to_start()
    root.update()
    assert application.start_screen.winfo_ismapped()
    assert len(application.start_screen.tree.get_children()) == 1

    application._duplicate_plan(folder)
    root.update()
    assert application.editor_frame.winfo_ismapped()
    assert application.current_folder != folder
    assert len(application.plan.items) == 1

    application._back_to_start()
    root.update()
    assert len(application.start_screen.tree.get_children()) == 2
