"""Integrationstest des gemeldeten Ablaufs:

  "Wenn ich das Symbol für Krone auf den Zahn 17 ziehe, dann soll die Kontur
   an den Zahn angepasst sein (also einen Molaren zeigen)" - und die
   Zahnnummer muss unten in der Liste stehen.
"""
import os

import pytest

tk = pytest.importorskip("tkinter")

from PIL import Image

pytestmark = pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="Kein Display verfuegbar")


class FakeEvent:
    def __init__(self, x, y):
        self.x, self.y = x, y


def _tk_available():
    try:
        root = tk.Tk()
        root.destroy()
        return True
    except tk.TclError:
        return False


@pytest.fixture()
def canvas_with_calibration():
    if not _tk_available():
        pytest.skip("Tk kann kein Fenster oeffnen")
    from behandlungsplaner.canvas_view import PlanCanvas
    from behandlungsplaner.models import TreatmentPlan

    root = tk.Tk()
    canvas = PlanCanvas(root, width=900, height=460)
    canvas.pack(fill="both", expand=True)
    root.update_idletasks()
    root.update()

    plan = TreatmentPlan(patient_name="Test")
    canvas.load(plan, Image.new("RGB", (2800, 1400), (100, 100, 100)))
    root.update()
    canvas.set_calibration_enabled(True)
    root.update()

    yield root, canvas, plan
    root.destroy()


def _canvas_point_of_tooth(canvas, plan, tooth):
    return canvas._frac_to_canvas(*plan.calibration_points[tooth])


def test_dropping_crown_on_tooth_17_assigns_number_and_molar_shape(canvas_with_calibration):
    from behandlungsplaner import tooth_anatomy as anat

    root, canvas, plan = canvas_with_calibration
    cx, cy = _canvas_point_of_tooth(canvas, plan, 17)

    canvas.begin_external_drag("krone")
    canvas.update_external_drag(cx, cy)
    canvas.end_external_drag(cx, cy)
    root.update()

    assert len(plan.items) == 1
    item = plan.items[0]
    assert item.fdi_tooth == 17
    assert anat.tooth_class_for(item.fdi_tooth) == "molar"


def test_dropping_slightly_off_target_still_assigns_the_tooth(canvas_with_calibration):
    """Der gemeldete Fehlerfall: man trifft den Kalibrierpunkt nicht exakt.
    Frueher blieb die Zahnnummer dabei leer."""
    root, canvas, plan = canvas_with_calibration
    cx, cy = _canvas_point_of_tooth(canvas, plan, 36)

    canvas.begin_external_drag("krone")
    canvas.end_external_drag(cx + 12, cy + 9)
    root.update()

    assert plan.items[0].fdi_tooth == 36


def test_crown_size_follows_the_tooth(canvas_with_calibration):
    """Ein Molar bekommt eine breitere Krone als ein Schneidezahn."""
    root, canvas, plan = canvas_with_calibration

    mx, my = _canvas_point_of_tooth(canvas, plan, 17)
    canvas.begin_external_drag("krone")
    canvas.end_external_drag(mx, my)

    ix, iy = _canvas_point_of_tooth(canvas, plan, 11)
    canvas.begin_external_drag("krone")
    canvas.end_external_drag(ix, iy)
    root.update()

    molar = next(i for i in plan.items if i.fdi_tooth == 17)
    incisor = next(i for i in plan.items if i.fdi_tooth == 11)
    assert molar.width > incisor.width


def test_moving_a_crown_to_another_tooth_updates_number_and_shape(canvas_with_calibration):
    """Kernfehler der Rueckmeldung: beim Verschieben wurde die Zahnnummer nie
    aktualisiert, die Liste blieb leer."""
    from behandlungsplaner import shapes

    root, canvas, plan = canvas_with_calibration

    start_x, start_y = _canvas_point_of_tooth(canvas, plan, 11)
    canvas.begin_external_drag("krone")
    canvas.end_external_drag(start_x, start_y)
    root.update()

    item = plan.items[0]
    assert item.fdi_tooth == 11
    shape_before = shapes.build_draw_ops(item, canvas.image_w, canvas.image_h)[0].points

    canvas.select_item(item.id)
    canvas._on_press(FakeEvent(start_x, start_y))
    target_x, target_y = _canvas_point_of_tooth(canvas, plan, 17)
    canvas._on_motion(FakeEvent(target_x, target_y))
    canvas._on_release(FakeEvent(target_x, target_y))
    root.update()

    assert item.fdi_tooth == 17
    shape_after = shapes.build_draw_ops(item, canvas.image_w, canvas.image_h)[0].points
    assert shape_after != shape_before


def test_manual_resize_survives_a_later_move(canvas_with_calibration):
    """Wer die Groesse selbst angepasst hat, soll sie beim Verschieben
    behalten - die Automatik darf sie dann nicht ueberschreiben."""
    root, canvas, plan = canvas_with_calibration

    sx, sy = _canvas_point_of_tooth(canvas, plan, 11)
    canvas.begin_external_drag("krone")
    canvas.end_external_drag(sx, sy)
    root.update()

    item = plan.items[0]
    canvas.select_item(item.id)
    assert item.auto_sized is True

    handle = canvas._handle_positions(item)["corner:2"]
    hx, hy = canvas.img_to_canvas(*handle)
    canvas._on_press(FakeEvent(hx, hy))
    canvas._on_motion(FakeEvent(hx + 40, hy + 30))
    canvas._on_release(FakeEvent(hx + 40, hy + 30))
    root.update()

    assert item.auto_sized is False
    custom_width = item.width

    canvas._on_press(FakeEvent(sx, sy))
    tx, ty = _canvas_point_of_tooth(canvas, plan, 17)
    canvas._on_motion(FakeEvent(tx, ty))
    canvas._on_release(FakeEvent(tx, ty))
    root.update()

    assert item.fdi_tooth == 17          # Zuordnung folgt weiterhin
    assert item.width == custom_width     # Groesse bleibt wie eingestellt


def test_region_symbol_is_not_forced_onto_a_tooth(canvas_with_calibration):
    """NICO/FDOK ist kieferregion-gebunden und soll keine Zahnnummer
    aufgedraengt bekommen."""
    root, canvas, plan = canvas_with_calibration
    cx, cy = _canvas_point_of_tooth(canvas, plan, 36)

    canvas.begin_external_drag("nico_fdok")
    canvas.end_external_drag(cx, cy)
    root.update()

    assert plan.items[0].fdi_tooth is None


def test_plan_list_shows_the_tooth_number_after_placing(canvas_with_calibration):
    """Die Rueckmeldung 'unten in der Liste soll die Zahnnummer stehen'."""
    from behandlungsplaner.plan_list_view import PlanListView

    root, canvas, plan = canvas_with_calibration
    cx, cy = _canvas_point_of_tooth(canvas, plan, 17)
    canvas.begin_external_drag("krone")
    canvas.end_external_drag(cx, cy)
    root.update()

    view = PlanListView(root)
    view.pack()
    view.refresh(plan)
    root.update()

    item = plan.items[0]
    cell = view.tree.set(item.id, "tooth")
    assert cell.startswith("17")
    assert "Molar" in cell


def test_drag_preview_marks_the_target_tooth(canvas_with_calibration):
    """Waehrend des Ziehens wird der Zielzahn hervorgehoben, damit vor dem
    Loslassen klar ist, welche Nummer vergeben wird."""
    root, canvas, plan = canvas_with_calibration
    cx, cy = _canvas_point_of_tooth(canvas, plan, 26)

    canvas.begin_external_drag("krone")
    canvas.update_external_drag(cx, cy)
    root.update()

    assert canvas._snap_target_tooth == 26
    assert canvas.find_withtag("dragpreview")      # Ghost sichtbar
    assert canvas.find_withtag("snaptarget")       # Zielmarkierung sichtbar

    canvas.end_external_drag(cx, cy)
    root.update()
    assert canvas._snap_target_tooth is None
    assert not canvas.find_withtag("dragpreview")


def test_drag_preview_uses_the_real_symbol_outline(canvas_with_calibration):
    """Die Vorschau zeigt die spaetere Kontur - nicht mehr nur einen Kreis."""
    root, canvas, plan = canvas_with_calibration
    cx, cy = _canvas_point_of_tooth(canvas, plan, 17)

    canvas.begin_external_drag("krone")
    canvas.update_external_drag(cx, cy)
    root.update()

    preview_ids = canvas.find_withtag("dragpreview")
    assert preview_ids
    # Eine Kronenkontur ist ein Polygon mit vielen Stuetzpunkten.
    polygons = [i for i in preview_ids if canvas.type(i) == "polygon"]
    assert polygons
    coords = canvas.coords(polygons[0])
    assert len(coords) / 2 > 8
