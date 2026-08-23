"""Tests fuer Palette, Planungsliste und Startbildschirm (Tkinter-Widgets ohne
die komplexe Canvas-Drag-Logik, die in test_canvas_view.py separat geprueft
wird). Erfordert ein (ggf. virtuelles) Display."""
import os

import pytest

tk = pytest.importorskip("tkinter")

pytestmark = pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="Kein Display verfuegbar")


def _tk_available():
    try:
        root = tk.Tk()
        root.destroy()
        return True
    except tk.TclError:
        return False


@pytest.fixture()
def root():
    if not _tk_available():
        pytest.skip("Tk kann kein Fenster oeffnen")
    r = tk.Tk()
    yield r
    r.destroy()


def test_palette_builds_all_entries_and_wires_drag(root):
    from PIL import Image

    from behandlungsplaner.canvas_view import PlanCanvas
    from behandlungsplaner.models import ALL_KINDS, TreatmentPlan
    from behandlungsplaner.palette import SymbolPalette

    canvas = PlanCanvas(root, width=400, height=300)
    canvas.pack()
    canvas.load(TreatmentPlan(), Image.new("RGB", (800, 400), (90, 90, 90)))
    root.update()

    palette = SymbolPalette(root)
    palette.set_target_canvas(canvas)
    palette.pack()
    root.update()

    # Fuer jede Befundart existiert genau eine Kachel.
    assert set(palette._tiles.keys()) == set(ALL_KINDS)

    canvas.begin_external_drag("krone")
    assert canvas._external_drag_kind == "krone"
    canvas.end_external_drag(200, 150)
    assert len(canvas.plan.items) == 1
    assert canvas.plan.items[0].kind == "krone"


def test_palette_click_arms_kind_and_canvas_click_places_it(root):
    """Klick-zum-Setzen als Alternative zum Ziehen: Kachel anklicken merkt die
    Befundart vor, der naechste Klick ins Bild setzt sie."""
    from PIL import Image

    from behandlungsplaner.canvas_view import PlanCanvas
    from behandlungsplaner.models import TreatmentPlan
    from behandlungsplaner.palette import SymbolPalette

    canvas = PlanCanvas(root, width=400, height=300)
    canvas.pack()
    canvas.load(TreatmentPlan(), Image.new("RGB", (800, 400), (90, 90, 90)))
    root.update()

    palette = SymbolPalette(root)
    palette.set_target_canvas(canvas)
    palette.on_armed_change = canvas.set_armed_kind
    canvas.on_armed_consumed = palette.clear_armed
    palette.pack()
    root.update()

    class FakeEvent:
        def __init__(self, x, y):
            self.x, self.y = x, y

    # Klick ohne Mausbewegung = vormerken (kein Ziehen).
    palette._on_press("implantat", None)
    palette._on_release("implantat", FakeEvent(0, 0))
    assert palette.armed_kind == "implantat"
    assert canvas._armed_kind == "implantat"

    canvas._on_press(FakeEvent(200, 150))
    root.update()

    assert len(canvas.plan.items) == 1
    assert canvas.plan.items[0].kind == "implantat"
    # Nach dem Setzen ist die Vormerkung wieder aufgehoben.
    assert canvas._armed_kind is None
    assert palette.armed_kind is None


def test_plan_list_view_refresh_edit_toggle_delete(root):
    from behandlungsplaner.models import KIND_IMPLANTAT, PlanItem, STATUS_DURCHGEFUEHRT, TreatmentPlan
    from behandlungsplaner.plan_list_view import PlanListView

    plan = TreatmentPlan(patient_name="Test")
    item = PlanItem(kind=KIND_IMPLANTAT, x=0.1, y=0.1, width=0.05, height=0.08, fdi_tooth=16, cost=1800)
    plan.add_item(item)

    view = PlanListView(root)
    view.pack()
    changes = []
    view.on_change = lambda: changes.append(1)
    view.refresh(plan)
    root.update()

    assert item.id in view.tree.get_children()
    assert "1.800,00" in view.total_label.cget("text")
    # Die Zahnnummer steht in der ersten Spalte, im Klartext.
    tooth_cell = view.tree.set(item.id, "tooth")
    assert tooth_cell.startswith("16")
    assert "Molar" in tooth_cell

    view.tree.selection_set(item.id)
    view._toggle_status()
    assert item.status == STATUS_DURCHGEFUEHRT
    assert changes  # on_change wurde aufgerufen

    view.tree.selection_set(item.id)
    view._delete_selected()
    assert plan.get_item(item.id) is None
    assert item.id not in view.tree.get_children()


def test_plan_list_view_select_row_sync(root):
    from behandlungsplaner.models import KIND_KRONE, PlanItem, TreatmentPlan
    from behandlungsplaner.plan_list_view import PlanListView

    plan = TreatmentPlan()
    item = plan.add_item(PlanItem(kind=KIND_KRONE, x=0.1, y=0.1, width=0.05, height=0.06, fdi_tooth=11))
    view = PlanListView(root)
    view.pack()
    view.refresh(plan)
    root.update()

    received = []
    view.on_row_selected = lambda item_id: received.append(item_id)
    view.tree.selection_set(item.id)
    root.update()
    assert received == [item.id]

    received.clear()
    view.select_row(item.id)  # programmatischer Sync darf KEIN Event ausloesen
    root.update()
    assert received == []


def test_start_screen_lists_plans_and_callbacks(root, tmp_path):
    from behandlungsplaner import storage
    from behandlungsplaner.models import TreatmentPlan
    from behandlungsplaner.start_screen import StartScreen

    plan = TreatmentPlan(patient_name="Anna Test", plan_date="2026-08-21")
    folder = storage.create_plan_folder(tmp_path, plan)
    storage.save_plan(plan, folder)

    screen = StartScreen(root, tmp_path)
    screen.pack()
    screen.refresh()
    root.update()

    assert len(screen.tree.get_children()) == 1

    opened = []
    screen.on_open = lambda f: opened.append(f)
    screen.tree.selection_set(str(folder))
    screen._open_selected()
    assert opened == [folder]

    duplicated = []
    screen.on_duplicate = lambda f: duplicated.append(f)
    screen._duplicate_selected()
    assert duplicated == [folder]
