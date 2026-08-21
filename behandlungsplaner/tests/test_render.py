import numpy as np
from PIL import Image

from behandlungsplaner import render
from behandlungsplaner.models import ALL_KINDS, KIND_BRUECKE, PlanItem, TreatmentPlan


def _base_image(w=600, h=300, color=(80, 80, 80)):
    return Image.new("RGB", (w, h), color)


def test_render_plan_keeps_image_size():
    img = _base_image()
    plan = TreatmentPlan()
    plan.add_item(PlanItem(kind="krone", x=0.5, y=0.5, width=0.1, height=0.15, fdi_tooth=16))
    out = render.render_plan(plan, img)
    assert out.size == img.size
    assert out.mode == "RGB"


def test_render_plan_actually_draws_something():
    img = _base_image(color=(80, 80, 80))
    plan = TreatmentPlan()
    plan.add_item(PlanItem(kind="krone", x=0.5, y=0.5, width=0.2, height=0.3, fdi_tooth=16))
    out = render.render_plan(plan, img)
    before = np.array(img)
    after = np.array(out)
    assert not np.array_equal(before, after)


def test_render_plan_fills_are_translucent_not_fully_opaque_blob():
    # Bei halbtransparenter Fuellung duerfen die Pixel im Symbolinneren nicht
    # exakt der reinen Symbolfarbe entsprechen (Hintergrund muss durchscheinen).
    img = _base_image(color=(10, 10, 10))
    plan = TreatmentPlan()
    plan.add_item(PlanItem(kind="krone", x=0.5, y=0.5, width=0.3, height=0.4, fdi_tooth=16))
    out = np.array(render.render_plan(plan, img))
    center = out[out.shape[0] // 2, out.shape[1] // 2]
    pure_fill = np.array([0xF3, 0xD6, 0x7C])
    assert not np.array_equal(center, pure_fill)


def test_render_all_kinds_without_error():
    img = _base_image()
    plan = TreatmentPlan()
    for kind in ALL_KINDS:
        kwargs = dict(kind=kind, x=0.3, y=0.4, width=0.08, height=0.12)
        if kind == KIND_BRUECKE:
            kwargs.update(end_x=0.5, end_y=0.4, bridge_teeth=[14, 15, 16], height=0.02)
        plan.add_item(PlanItem(**kwargs))
    out = render.render_plan(plan, img)
    assert out.size == img.size


def test_render_with_calibration_points():
    img = _base_image()
    plan = TreatmentPlan()
    plan.calibration_points = {18: (0.05, 0.2), 11: (0.45, 0.2)}
    out_with = render.render_plan(plan, img, show_calibration=True)
    out_without = render.render_plan(plan, img, show_calibration=False)
    assert not np.array_equal(np.array(out_with), np.array(out_without))


def test_legend_strip_contains_all_kinds():
    strip = render.render_legend_strip(800)
    assert strip.width == 800
    assert strip.height > 0


def test_render_plan_with_legend_is_taller_than_plain_render():
    img = _base_image()
    plan = TreatmentPlan()
    plan.add_item(PlanItem(kind="implantat", x=0.5, y=0.5, width=0.1, height=0.15, fdi_tooth=36))
    plain = render.render_plan(plan, img)
    combined = render.render_plan_with_legend(plan, img)
    assert combined.width == plain.width
    assert combined.height > plain.height


def test_dashed_polyline_produces_shorter_total_than_solid():
    points = [(0, 0), (100, 0), (100, 100), (0, 100)]
    segments = render._dashed_polyline(points, dash=(5, 5), closed=True)
    total_dashed = sum(
        ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 for (x0, y0), (x1, y1) in segments
    )
    perimeter = 400
    assert 0 < total_dashed < perimeter
