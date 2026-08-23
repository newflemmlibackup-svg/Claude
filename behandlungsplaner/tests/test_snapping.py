"""Tests der Zahn-Zuordnungslogik - bewusst ohne Tkinter, damit sie die
reine Geometrie pruefen und nicht von Zoomstufe/Fenstergroesse abhaengen."""
import pytest

from behandlungsplaner import snapping
from behandlungsplaner.fdi import default_calibration_layout
from behandlungsplaner.models import KIND_IMPLANTAT, KIND_KRONE

IMAGE_W, IMAGE_H = 2800, 1400


@pytest.fixture()
def layout():
    return default_calibration_layout()


def test_dropping_exactly_on_a_tooth_assigns_it(layout):
    for tooth in (17, 36, 11, 48):
        fx, fy = layout[tooth]
        assert snapping.nearest_tooth(layout, fx, fy, IMAGE_W, IMAGE_H) == tooth


def test_dropping_roughly_near_a_tooth_still_assigns_it(layout):
    """Der eigentliche Praxisfall: man trifft den Kalibrierpunkt nicht pixelgenau.
    Frueher (fixer 26-Pixel-Radius) blieb die Zuordnung dabei leer."""
    tooth = 17
    fx, fy = layout[tooth]
    spacing_px = snapping.local_spacing_px(layout, tooth, IMAGE_W, IMAGE_H)
    # Ein halber Zahnabstand daneben - deutlich mehr als 26 Pixel.
    offset_frac = (spacing_px * 0.5) / IMAGE_H
    assert spacing_px * 0.5 > 26, "Testaufbau soll den alten Radius klar ueberschreiten"

    assert snapping.nearest_tooth(layout, fx, fy + offset_frac, IMAGE_W, IMAGE_H) == tooth


def test_far_away_position_is_not_assigned(layout):
    # Deutlich ausserhalb beider Zahnboegen (unterer Bildrand unterhalb der
    # Mandibula bzw. obere Bildecke im Sinus-/Kiefergelenkbereich).
    assert snapping.nearest_tooth(layout, 0.5, 0.99, IMAGE_W, IMAGE_H) is None
    assert snapping.nearest_tooth(layout, 0.97, 0.02, IMAGE_W, IMAGE_H) is None


def test_midline_between_the_arches_is_not_greedily_assigned(layout):
    # Genau mittig zwischen Ober- und Unterkiefer soll keine Zuordnung
    # erzwungen werden - dort ist nicht entscheidbar, welcher Bogen gemeint ist.
    assert snapping.nearest_tooth(layout, 0.5, 0.5, IMAGE_W, IMAGE_H) is None


def test_nearest_tooth_picks_the_closest_of_two_neighbors(layout):
    a, b = 16, 15
    ax, ay = layout[a]
    bx, by = layout[b]
    # Knapp auf der Seite von a zwischen beiden Zaehnen.
    fx = ax + (bx - ax) * 0.3
    fy = ay + (by - ay) * 0.3
    assert snapping.nearest_tooth(layout, fx, fy, IMAGE_W, IMAGE_H) == a


def test_snap_position_magnets_when_close_and_stays_free_when_not(layout):
    tooth = 26
    tx, ty = layout[tooth]
    spacing_px = snapping.local_spacing_px(layout, tooth, IMAGE_W, IMAGE_H)

    # Sehr nah: Position rastet exakt auf den Zahn ein.
    near_offset = (spacing_px * 0.15) / IMAGE_W
    sx, sy, snapped = snapping.snap_position(layout, tx + near_offset, ty, IMAGE_W, IMAGE_H)
    assert snapped == tooth
    assert (sx, sy) == (tx, ty)

    # Weiter weg, aber noch im Zuordnungsbereich: Zahn ja, Position frei.
    # Versatz senkrecht zum Zahnbogen (nach apikal), damit weiterhin derselbe
    # Zahn der naechste bleibt - seitlich waere ab ~0.5 der Nachbar naeher.
    far_offset = (spacing_px * 0.7) / IMAGE_H
    sx2, sy2, snapped2 = snapping.snap_position(layout, tx, ty + far_offset, IMAGE_W, IMAGE_H)
    assert snapped2 == tooth
    assert sy2 == pytest.approx(ty + far_offset)


def test_sideways_drift_hands_over_to_the_neighbor_tooth(layout):
    """Zieht man ueber die Mitte zwischen zwei Zaehnen hinaus, uebernimmt der
    Nachbarzahn - Grundlage dafuer, dass sich die Kontur beim Verschieben
    laufend an den richtigen Zahn anpasst."""
    tx, ty = layout[26]
    nx, ny = layout[27]
    just_past_middle_x = tx + (nx - tx) * 0.6
    just_past_middle_y = ty + (ny - ty) * 0.6
    assert snapping.nearest_tooth(
        layout, just_past_middle_x, just_past_middle_y, IMAGE_W, IMAGE_H) == 27


def test_local_spacing_matches_actual_neighbor_distance(layout):
    import math
    tooth = 16
    spacing = snapping.local_spacing_px(layout, tooth, IMAGE_W, IMAGE_H)
    own = (layout[16][0] * IMAGE_W, layout[16][1] * IMAGE_H)
    neighbors = [
        (layout[17][0] * IMAGE_W, layout[17][1] * IMAGE_H),
        (layout[15][0] * IMAGE_W, layout[15][1] * IMAGE_H),
    ]
    expected = min(math.dist(own, n) for n in neighbors)
    assert spacing == pytest.approx(expected)


def test_local_spacing_falls_back_without_neighbors():
    lonely = {16: (0.5, 0.3)}
    spacing = snapping.local_spacing_px(lonely, 16, IMAGE_W, IMAGE_H)
    assert spacing > 0


def test_fit_box_scales_molar_wider_than_incisor(layout):
    molar_w, molar_h = snapping.fit_box_for_tooth(KIND_KRONE, 17, layout, IMAGE_W, IMAGE_H)
    incisor_w, incisor_h = snapping.fit_box_for_tooth(KIND_KRONE, 11, layout, IMAGE_W, IMAGE_H)

    molar_ratio = (molar_w * IMAGE_W) / (molar_h * IMAGE_H)
    incisor_ratio = (incisor_w * IMAGE_W) / (incisor_h * IMAGE_H)
    # Ein Molar ist im Verhaeltnis deutlich breiter als ein Schneidezahn.
    assert molar_ratio > incisor_ratio


def test_fit_box_uses_fallback_without_calibration():
    w, h = snapping.fit_box_for_tooth(KIND_KRONE, None, {}, IMAGE_W, IMAGE_H,
                                       fallback_width_fraction=0.05)
    assert w == pytest.approx(0.05)
    assert h > 0


def test_implant_is_narrower_than_crown_on_same_tooth(layout):
    crown_w, _ = snapping.fit_box_for_tooth(KIND_KRONE, 36, layout, IMAGE_W, IMAGE_H)
    implant_w, _ = snapping.fit_box_for_tooth(KIND_IMPLANTAT, 36, layout, IMAGE_W, IMAGE_H)
    assert implant_w < crown_w
