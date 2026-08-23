"""Anker anlegen und auf einem veraenderten Bildschirm wiederfinden."""
from __future__ import annotations

import pytest

from klickpilot.anchors import AnchorFactory, AnchorLocator, AnchorNotFound
from klickpilot.screen import Frame

from .conftest import FakeScreen


def make_anchor(store, config, ui, row=1, origin=(300, 200), identical=False, scale=2.0):
    slug = store.create("Test")
    frame = Frame(ui.render(origin, identical_buttons=identical), (0.0, 0.0), scale, 1)
    pixel = ui.button_center(row, origin)
    point = (pixel[0] / scale, pixel[1] / scale)
    anchor = AnchorFactory(store, slug, config).make(frame, point)
    return slug, anchor, point


def test_anchor_stores_template_and_context(store, config, ui):
    slug, anchor, point = make_anchor(store, config, ui)
    assert store.asset_path(slug, anchor.template).exists()
    assert store.asset_path(slug, anchor.context).exists()
    # Der Klickpunkt liegt mitten in der Schablone.
    assert anchor.hotspot[0] == pytest.approx(anchor.size[0] / 2, abs=1)
    assert anchor.point == pytest.approx(point)
    assert anchor.scale == 2.0


def test_finds_element_after_window_moved(store, config, ui):
    slug, anchor, _point = make_anchor(store, config, ui)
    screen = FakeScreen(ui.render((1200, 780)))
    located = AnchorLocator(screen, store, config).locate_once(slug, anchor)
    expected = ui.button_center(1, (1200, 780))
    assert located.score > 0.9
    assert located.point[0] * 2 == pytest.approx(expected[0], abs=3)
    assert located.point[1] * 2 == pytest.approx(expected[1], abs=3)


def test_finds_element_after_brightness_change(store, config, ui):
    slug, anchor, _point = make_anchor(store, config, ui)
    screen = FakeScreen(ui.render((500, 400), brightness=-35))
    located = AnchorLocator(screen, store, config).locate_once(slug, anchor)
    assert located.score > 0.85


def test_context_picks_the_right_row_among_identical_buttons(store, config, ui):
    """Zehn gleich aussehende Knoepfe: erst die Umgebung entscheidet."""
    narrow = dict(config)
    narrow.update({"template_size": [40, 25], "context_size": [300, 160], "context_weight": 0.5})
    slug, anchor, _point = make_anchor(store, narrow, ui, row=2, identical=True)

    screen = FakeScreen(ui.render((900, 600), identical_buttons=True))
    located = AnchorLocator(screen, store, narrow).locate_once(slug, anchor)
    expected = ui.button_center(2, (900, 600))
    assert located is not None
    assert located.point[1] * 2 == pytest.approx(expected[1], abs=6), "falsche Zeile getroffen"
    assert located.point[0] * 2 == pytest.approx(expected[0], abs=6)


def test_missing_element_raises_after_timeout(store, config, ui):
    slug, anchor, _point = make_anchor(store, config, ui)
    empty = FakeScreen(ui.background.copy())
    locator = AnchorLocator(empty, store, config)
    with pytest.raises(AnchorNotFound) as problem:
        locator.locate(slug, anchor, timeout=0.1)
    assert "nicht gefunden" in str(problem.value)


def test_wait_until_gone(store, config, ui):
    slug, anchor, _point = make_anchor(store, config, ui)
    present = FakeScreen(ui.render((300, 200)))
    locator = AnchorLocator(present, store, config)
    assert locator.wait_until_gone(slug, anchor, timeout=0.1) is False
    present.show(ui.background.copy())
    assert locator.wait_until_gone(slug, anchor, timeout=0.5) is True


def test_search_covers_second_display(store, config, ui):
    """Wurde auf Bildschirm 1 aufgenommen, wird auch Bildschirm 2 durchsucht."""
    slug, anchor, _point = make_anchor(store, config, ui)
    anchor.display_id = 99  # Bildschirm gibt es nicht mehr
    screen = FakeScreen(ui.render((640, 480)))
    located = AnchorLocator(screen, store, config).locate_once(slug, anchor)
    assert located is not None and located.score > 0.9


def test_stops_early_once_threshold_is_reached(store, config, ui):
    slug, anchor, _point = make_anchor(store, config, ui)
    screen = FakeScreen(ui.render((300, 200)))
    AnchorLocator(screen, store, config).locate(slug, anchor, timeout=2.0)
    assert screen.captures == 1, "es wurde unnoetig weiter fotografiert"
