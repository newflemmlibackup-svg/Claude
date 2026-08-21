import math

import pytest

from behandlungsplaner.models import ALL_KINDS, KIND_BRUECKE, PlanItem
from behandlungsplaner import shapes


IMAGE_W, IMAGE_H = 3000, 1500


def _make_item(kind, **overrides):
    kwargs = dict(kind=kind, x=0.5, y=0.5, width=0.05, height=0.08)
    kwargs.update(overrides)
    if kind == KIND_BRUECKE:
        kwargs.setdefault("end_x", 0.6)
        kwargs.setdefault("end_y", 0.5)
        kwargs.setdefault("bridge_teeth", [14, 15, 16])
    return PlanItem(**kwargs)


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_build_draw_ops_returns_something_for_every_kind(kind):
    item = _make_item(kind)
    ops = shapes.build_draw_ops(item, IMAGE_W, IMAGE_H)
    assert len(ops) > 0
    for op in ops:
        assert op.kind in ("polygon", "line", "text")
        assert len(op.points) >= 1
        for x, y in op.points:
            assert math.isfinite(x) and math.isfinite(y)


def test_simple_shape_is_centered_at_item_position():
    item = _make_item("implantat", x=0.25, y=0.75, width=0.04, height=0.1)
    x0, y0, x1, y1 = shapes.bounding_box(item, IMAGE_W, IMAGE_H)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    assert cx == pytest.approx(item.x * IMAGE_W, abs=2)
    assert cy == pytest.approx(item.y * IMAGE_H, abs=2)


def test_bounding_box_scales_with_width_height():
    small = _make_item("krone", width=0.02, height=0.03)
    large = _make_item("krone", width=0.08, height=0.12)
    x0s, y0s, x1s, y1s = shapes.bounding_box(small, IMAGE_W, IMAGE_H)
    x0l, y0l, x1l, y1l = shapes.bounding_box(large, IMAGE_W, IMAGE_H)
    assert (x1l - x0l) > (x1s - x0s)
    assert (y1l - y0l) > (y1s - y0s)


def test_rotation_changes_geometry_but_not_center():
    item0 = _make_item("krone", rotation=0)
    item90 = _make_item("krone", rotation=90)
    ops0 = shapes.build_draw_ops(item0, IMAGE_W, IMAGE_H)
    ops90 = shapes.build_draw_ops(item90, IMAGE_W, IMAGE_H)
    assert ops0[0].points != ops90[0].points

    bb0 = shapes.bounding_box(item0, IMAGE_W, IMAGE_H)
    bb90 = shapes.bounding_box(item90, IMAGE_W, IMAGE_H)
    c0 = ((bb0[0] + bb0[2]) / 2, (bb0[1] + bb0[3]) / 2)
    c90 = ((bb90[0] + bb90[2]) / 2, (bb90[1] + bb90[3]) / 2)
    assert c0[0] == pytest.approx(c90[0], abs=2)
    assert c0[1] == pytest.approx(c90[1], abs=2)


def test_bruecke_spans_between_start_and_end_point():
    item = _make_item(KIND_BRUECKE, x=0.2, y=0.4, end_x=0.4, end_y=0.42, height=0.02)
    ops = shapes.build_draw_ops(item, IMAGE_W, IMAGE_H)
    bar = ops[0]
    assert bar.kind == "polygon"
    xs = [p[0] for p in bar.points]
    assert min(xs) < 0.2 * IMAGE_W + 5
    assert max(xs) > 0.4 * IMAGE_W - 5

    # Ein Querstrich pro ueberspanntem Zahn (Pfeiler + Zwischenglieder).
    tick_ops = [op for op in ops[1:] if op.kind == "line"]
    assert len(tick_ops) == len(item.bridge_teeth)


def test_bruecke_without_bridge_teeth_still_draws_two_ticks():
    item = _make_item(KIND_BRUECKE, bridge_teeth=None)
    ops = shapes.build_draw_ops(item, IMAGE_W, IMAGE_H)
    tick_ops = [op for op in ops[1:] if op.kind == "line"]
    assert len(tick_ops) == 2


def test_legend_entries_cover_all_kinds():
    entries = shapes.legend_entries()
    kinds = {k for k, _label, _color in entries}
    assert kinds == set(ALL_KINDS)
