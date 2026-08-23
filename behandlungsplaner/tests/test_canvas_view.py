"""Funktionstest der Canvas-Interaktionslogik (Resize/Rotate/Snap/Bruecke).

Ruft die privaten Event-Handler direkt mit synthetischen Event-Objekten auf,
statt echte OS-Mausereignisse zu erzeugen - das prueft die Geometrie-/
Snapping-Logik praezise und deterministisch. Erfordert ein (ggf. virtuelles)
Display; wird sonst uebersprungen.
"""
import math
import os

import pytest

tk = pytest.importorskip("tkinter")

from PIL import Image

pytestmark = pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="Kein Display verfuegbar")


class FakeEvent:
    def __init__(self, x, y, delta=0):
        self.x = x
        self.y = y
        self.delta = delta


def _tk_available():
    try:
        root = tk.Tk()
        root.destroy()
        return True
    except tk.TclError:
        return False


@pytest.fixture()
def canvas_setup():
    if not _tk_available():
        pytest.skip("Tk kann kein Fenster oeffnen")
    from behandlungsplaner.canvas_view import PlanCanvas
    from behandlungsplaner.models import KIND_BRUECKE, KIND_KRONE, PlanItem, TreatmentPlan

    root = tk.Tk()
    canvas = PlanCanvas(root, width=800, height=400)
    canvas.pack(fill="both", expand=True)
    root.update_idletasks()
    root.geometry("800x400")
    root.update()

    plan = TreatmentPlan(patient_name="Test")
    image = Image.new("RGB", (1600, 800), (100, 100, 100))
    canvas.load(plan, image)
    root.update()

    yield root, canvas, plan
    root.destroy()


def test_fit_is_deferred_until_the_widget_has_a_real_size():
    """Regressionsschutz: wird direkt nach dem Erzeugen eingepasst, meldet Tk
    noch 1x1 Pixel. Frueher entstand daraus ein Mikro-Zoom und das
    Roentgenbild war praktisch unsichtbar - und wurde nie neu eingepasst."""
    if not _tk_available():
        pytest.skip("Tk kann kein Fenster oeffnen")
    from behandlungsplaner.canvas_view import PlanCanvas
    from behandlungsplaner.models import TreatmentPlan

    root = tk.Tk()
    try:
        canvas = PlanCanvas(root, width=800, height=400)
        # BEWUSST vor pack()/update(): das Widget hat noch keine Groesse.
        canvas.load(TreatmentPlan(), Image.new("RGB", (2400, 1200), (90, 90, 90)))
        canvas.zoom_fit()
        assert canvas._needs_fit is True, "Einpassen muss aufgeschoben werden"

        canvas.pack(fill="both", expand=True)
        root.update()

        assert canvas._needs_fit is False
        # Das Bild muss den Grossteil der Canvasbreite ausfuellen.
        assert canvas.image_w * canvas.zoom > canvas.winfo_width() * 0.5
    finally:
        root.destroy()


def test_zoom_fit_centers_image(canvas_setup):
    root, canvas, plan = canvas_setup
    assert canvas.zoom > 0
    x0, y0 = canvas.img_to_canvas(0, 0)
    x1, y1 = canvas.img_to_canvas(canvas.image_w, canvas.image_h)
    assert x1 - x0 == pytest.approx(canvas.image_w * canvas.zoom)


def test_place_new_item_without_calibration(canvas_setup):
    root, canvas, plan = canvas_setup
    canvas._place_new_item("krone", 400, 200)
    assert len(plan.items) == 1
    item = plan.items[0]
    assert item.kind == "krone"
    assert item.fdi_tooth is None
    fx, fy = canvas._canvas_to_frac(400, 200)
    assert item.x == pytest.approx(fx, abs=1e-6)


def test_place_new_item_with_calibration_snaps_and_sizes(canvas_setup):
    root, canvas, plan = canvas_setup
    canvas.set_calibration_enabled(True)
    assert plan.calibration_enabled
    assert len(plan.calibration_points) == 32

    tooth = 16
    fx, fy = plan.calibration_points[tooth]
    cx, cy = canvas._frac_to_canvas(fx, fy)
    canvas._place_new_item("krone", cx, cy)

    assert len(plan.items) == 1
    item = plan.items[0]
    assert item.fdi_tooth == tooth
    assert item.x == pytest.approx(fx, abs=1e-6)
    assert item.width > 0


def test_select_move_and_delete(canvas_setup):
    root, canvas, plan = canvas_setup
    canvas._place_new_item("implantat", 400, 200)
    item = plan.items[0]
    canvas.select_item(item.id)
    assert canvas.selected_item_id == item.id

    cx0, cy0 = canvas.img_to_canvas(item.x * canvas.image_w, item.y * canvas.image_h)
    canvas._on_press(FakeEvent(cx0, cy0))
    assert canvas._drag["mode"] == "move"
    canvas._on_motion(FakeEvent(cx0 + 50, cy0 + 20))
    canvas._on_release(FakeEvent(cx0 + 50, cy0 + 20))

    moved = plan.get_item(item.id)
    new_fx, new_fy = canvas._canvas_to_frac(cx0 + 50, cy0 + 20)
    assert moved.x == pytest.approx(new_fx, abs=1e-6)

    canvas.delete_selected()
    assert plan.get_item(item.id) is None
    assert canvas.selected_item_id is None


def test_resize_via_corner_handle_keeps_opposite_corner_fixed(canvas_setup):
    from behandlungsplaner import shapes
    root, canvas, plan = canvas_setup
    canvas._place_new_item("krone", 400, 200)
    item = plan.items[0]
    item.width, item.height = 0.05, 0.08
    item.rotation = 0.0
    canvas.select_item(item.id)

    x0, y0, x1, y1 = shapes.bounding_box(item, canvas.image_w, canvas.image_h)
    opposite_before = (x0, y0)  # obere linke Ecke bleibt fix bei Ziehen der unteren rechten (corner 2)

    handle_positions = canvas._handle_positions(item)
    hx, hy = canvas.img_to_canvas(*handle_positions["corner:2"])
    canvas._on_press(FakeEvent(hx, hy))
    assert canvas._drag["mode"] == "resize"

    new_hx, new_hy = hx + 80, hy + 40
    canvas._on_motion(FakeEvent(new_hx, new_hy))
    canvas._on_release(FakeEvent(new_hx, new_hy))

    resized = plan.get_item(item.id)
    nx0, ny0, nx1, ny1 = shapes.bounding_box(resized, canvas.image_w, canvas.image_h)
    assert (nx0, ny0) == pytest.approx(opposite_before, abs=1.0)
    assert (nx1 - nx0) > (x1 - x0)
    assert (ny1 - ny0) > (y1 - y0)


def test_resize_respects_rotation(canvas_setup):
    from behandlungsplaner import shapes
    root, canvas, plan = canvas_setup
    canvas._place_new_item("krone", 400, 200)
    item = plan.items[0]
    item.width, item.height, item.rotation = 0.05, 0.08, 45.0
    canvas.select_item(item.id)

    handle_positions = canvas._handle_positions(item)
    hx, hy = canvas.img_to_canvas(*handle_positions["corner:2"])
    canvas._on_press(FakeEvent(hx, hy))
    # Entlang der lokalen Diagonale nach aussen ziehen (bei 45 Grad Rotation
    # entspricht das ungefaehr einer reinen Vertikalbewegung im Bildraum).
    canvas._on_motion(FakeEvent(hx, hy + 60))
    canvas._on_release(FakeEvent(hx, hy + 60))

    resized = plan.get_item(item.id)
    assert resized.width * canvas.image_w > 1
    assert resized.height * canvas.image_h > 1
    assert resized.rotation == pytest.approx(45.0)


def test_rotate_handle_sets_rotation(canvas_setup):
    root, canvas, plan = canvas_setup
    canvas._place_new_item("krone", 400, 200)
    item = plan.items[0]
    canvas.select_item(item.id)

    handle_positions = canvas._handle_positions(item)
    hx, hy = canvas.img_to_canvas(*handle_positions["rotate"])
    canvas._on_press(FakeEvent(hx, hy))
    assert canvas._drag["mode"] == "rotate"

    cx, cy = canvas.img_to_canvas(item.x * canvas.image_w, item.y * canvas.image_h)
    # 90 Grad im Uhrzeigersinn: Greifpunkt nach rechts von der Mitte bewegen.
    canvas._on_motion(FakeEvent(cx + 100, cy))
    canvas._on_release(FakeEvent(cx + 100, cy))

    rotated = plan.get_item(item.id)
    assert rotated.rotation == pytest.approx(90.0, abs=1.0)


def test_calibration_point_drag_updates_position(canvas_setup):
    root, canvas, plan = canvas_setup
    canvas.set_calibration_enabled(True)
    canvas.set_calibration_edit_mode(True)
    tooth = 11
    fx, fy = plan.calibration_points[tooth]
    cx, cy = canvas._frac_to_canvas(fx, fy)

    canvas._on_press(FakeEvent(cx, cy))
    assert canvas._drag["mode"] == "calib"
    canvas._on_motion(FakeEvent(cx + 30, cy + 15))
    canvas._on_release(FakeEvent(cx + 30, cy + 15))

    new_fx, new_fy = plan.calibration_points[tooth]
    assert (new_fx, new_fy) != (fx, fy)


def test_calibration_points_are_not_grabbed_outside_edit_mode(canvas_setup):
    """Ohne Kalibriermodus muss ein Symbol, das auf seinem Rasterpunkt liegt,
    weiterhin greifbar sein - sonst liesse es sich nie wieder verschieben."""
    root, canvas, plan = canvas_setup
    canvas.set_calibration_enabled(True)
    tooth = 11
    fx, fy = plan.calibration_points[tooth]
    cx, cy = canvas._frac_to_canvas(fx, fy)

    canvas._place_new_item("krone", cx, cy)
    item = plan.items[0]
    canvas.select_item(item.id)

    canvas._on_press(FakeEvent(cx, cy))
    assert canvas._drag is not None
    assert canvas._drag["mode"] == "move"
    assert canvas._drag["item_id"] == item.id


def test_bridge_endpoints_snap_and_compute_bridge_teeth(canvas_setup):
    root, canvas, plan = canvas_setup
    canvas.set_calibration_enabled(True)

    from behandlungsplaner.models import KIND_BRUECKE, PlanItem
    fx14, fy14 = plan.calibration_points[14]
    item = PlanItem(kind=KIND_BRUECKE, x=fx14, y=fy14, width=0.05, height=0.02,
                    end_x=fx14 + 0.02, end_y=fy14)
    plan.add_item(item)
    canvas.select_item(item.id)

    handle_positions = canvas._handle_positions(item)
    hx, hy = canvas.img_to_canvas(*handle_positions["bridge_end"])
    canvas._on_press(FakeEvent(hx, hy))
    assert canvas._drag["mode"] == "bridge_end"

    fx16, fy16 = plan.calibration_points[16]
    target_cx, target_cy = canvas._frac_to_canvas(fx16, fy16)
    canvas._on_motion(FakeEvent(target_cx, target_cy))
    canvas._on_release(FakeEvent(target_cx, target_cy))

    updated = plan.get_item(item.id)
    assert updated.end_x == pytest.approx(fx16, abs=1e-6)
    assert updated.bridge_teeth == [16, 15, 14]
