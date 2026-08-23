"""Prueft, dass sich die Symbolkontur tatsaechlich nach dem versorgten Zahn
richtet - der zentrale Punkt der Rueckmeldung "Krone auf Zahn 17 soll einen
Molaren zeigen"."""
import pytest

from behandlungsplaner import shapes
from behandlungsplaner import tooth_anatomy as anat
from behandlungsplaner.models import (
    KIND_EXTRAKTION,
    KIND_FEHLENDER_ZAHN,
    KIND_IMPLANTAT,
    KIND_KRONE,
    KIND_WURZELBEHANDLUNG,
    PlanItem,
)

IMAGE_W, IMAGE_H = 3000, 1500


def _crown_on(tooth):
    return PlanItem(kind=KIND_KRONE, x=0.5, y=0.5, width=0.06, height=0.05, fdi_tooth=tooth)


def _outline_points(item):
    ops = shapes.build_draw_ops(item, IMAGE_W, IMAGE_H)
    return ops[0].points


def _count_cusps(edge_points):
    """Zaehlt Hoeckerspitzen auf einer Kaufflaechenkontur (lokale
    Koordinaten, okklusal = kleinstes y). Verwendet eine Totzone, damit die
    Abtastpunkte der Hoeckerkurve nicht als eigene Spitzen zaehlen."""
    ys = [y for _x, y in edge_points]
    span = max(ys) - min(ys)
    if span <= 1e-9:
        return 0
    deadband = span * 0.05

    cusps = 0
    descending = False
    last_extreme = ys[0]
    for y in ys[1:]:
        if y < last_extreme - deadband:
            descending = True
            last_extreme = y
        elif y > last_extreme + deadband:
            if descending:
                cusps += 1      # Wendepunkt: eine Spitze abgeschlossen
                descending = False
            last_extreme = y
    if descending:
        cusps += 1              # Kontur endet auf einer Spitze
    return cusps


@pytest.mark.parametrize("tooth,expected_class", [
    (17, "molar"), (16, "molar"), (38, "molar"),
    (15, "praemolar"), (24, "praemolar"),
    (13, "eckzahn"), (43, "eckzahn"),
    (11, "schneidezahn"), (32, "schneidezahn"),
])
def test_tooth_class_mapping(tooth, expected_class):
    assert anat.tooth_class_for(tooth) == expected_class


def test_molar_crown_is_wider_relative_to_height_than_incisor_crown():
    molar = _crown_on(17)
    incisor = _crown_on(11)
    mx0, my0, mx1, my1 = shapes.bounding_box(molar, IMAGE_W, IMAGE_H)
    ix0, iy0, ix1, iy1 = shapes.bounding_box(incisor, IMAGE_W, IMAGE_H)

    # Bei identischer Box unterscheidet sich die tatsaechlich genutzte Breite
    # der Kontur: der Molar fuellt sie fast aus, der Schneidezahn bleibt schmal.
    molar_width = max(p[0] for p in _outline_points(molar)) - min(p[0] for p in _outline_points(molar))
    incisor_width = max(p[0] for p in _outline_points(incisor)) - min(p[0] for p in _outline_points(incisor))
    assert molar_width > incisor_width


@pytest.mark.parametrize("tooth_class,expected_cusps", [
    ("molar", 4), ("praemolar", 2), ("eckzahn", 1),
])
def test_cusp_count_per_tooth_class(tooth_class, expected_cusps):
    """Der sichtbarste anatomische Unterschied: die Hoeckerzahl."""
    edge = anat.occlusal_edge(tooth_class, half_width=0.5, tip_y=-0.5, valley_y=-0.37)
    assert _count_cusps(edge) == expected_cusps


def test_incisor_has_a_flat_edge_instead_of_cusps():
    tip_y = -0.5
    edge = anat.occlusal_edge("schneidezahn", half_width=0.31, tip_y=tip_y, valley_y=-0.42)
    assert _count_cusps(edge) == 1  # eine durchgehende Schneidekante, keine Hoecker
    # Die Schneidekante verlaeuft auf konstanter Hoehe (keine Hoeckerkurve).
    on_edge = [y for _x, y in edge if y == pytest.approx(tip_y)]
    assert len(on_edge) == 2


def test_rendered_crowns_differ_between_tooth_classes():
    """Auf der gerenderten Kontur (nicht nur im Anatomie-Modul) muessen sich
    die Zahnklassen unterscheiden."""
    outlines = {tooth: _outline_points(_crown_on(tooth)) for tooth in (47, 45, 43, 41)}
    seen = []
    for points in outlines.values():
        assert points not in seen
        seen.append(points)


def test_upper_and_lower_crowns_are_mirrored():
    """Oberkieferkronen zeigen die Kaufflaeche nach unten, Unterkieferkronen
    nach oben - sonst stuenden die Symbole auf dem Kopf."""
    upper = _outline_points(_crown_on(17))
    lower = _outline_points(_crown_on(47))

    centre_y = 0.5 * IMAGE_H
    # Schwerpunkt der Kontur relativ zur Symbolmitte: bei gespiegelten
    # Konturen liegen die Schwerpunkte auf entgegengesetzten Seiten.
    upper_offset = sum(p[1] for p in upper) / len(upper) - centre_y
    lower_offset = sum(p[1] for p in lower) / len(lower) - centre_y
    assert upper_offset * lower_offset < 0


def test_shape_changes_when_tooth_assignment_changes():
    """Verschiebt man ein Symbol von einem Schneidezahn auf einen Molaren,
    muss sich die Kontur mitaendern."""
    item = _crown_on(11)
    before = _outline_points(item)
    item.fdi_tooth = 17
    after = _outline_points(item)
    assert before != after


def test_unassigned_tooth_still_renders_a_sensible_default():
    item = PlanItem(kind=KIND_KRONE, x=0.5, y=0.5, width=0.06, height=0.05)
    ops = shapes.build_draw_ops(item, IMAGE_W, IMAGE_H)
    assert ops and len(ops[0].points) > 3


@pytest.mark.parametrize("kind", [KIND_EXTRAKTION, KIND_WURZELBEHANDLUNG, KIND_FEHLENDER_ZAHN])
def test_full_tooth_kinds_draw_more_roots_for_molars(kind):
    molar = PlanItem(kind=kind, x=0.5, y=0.5, width=0.06, height=0.08, fdi_tooth=46)
    incisor = PlanItem(kind=kind, x=0.5, y=0.5, width=0.06, height=0.08, fdi_tooth=41)
    molar_polys = [op for op in shapes.build_draw_ops(molar, IMAGE_W, IMAGE_H)
                   if op.kind == "polygon"]
    incisor_polys = [op for op in shapes.build_draw_ops(incisor, IMAGE_W, IMAGE_H)
                     if op.kind == "polygon"]
    # Molar: Krone + 2 Wurzeln, Frontzahn: Krone + 1 Wurzel.
    assert len(molar_polys) == len(incisor_polys) + 1


def test_root_canal_lines_reach_the_apex():
    """Regressionsschutz: die Kanaellinien wurden frueher ueber einen festen
    Punktindex bestimmt und endeten nach einer Formaenderung mitten im Zahn."""
    top_y, bottom_y = -0.04, 0.5
    for tooth_class in anat.ALL_TOOTH_CLASSES:
        lines = anat.root_canal_lines(tooth_class, top_y=top_y, bottom_y=bottom_y)
        assert len(lines) == anat.ROOT_COUNT[tooth_class]
        for (_sx, sy), (_ex, ey) in lines:
            assert sy == pytest.approx(top_y)
            # Endpunkt kurz vor dem Apex, nicht auf halber Strecke.
            assert ey > top_y + (bottom_y - top_y) * 0.85


def test_implant_shape_is_tooth_independent():
    """Implantate sind Normteile - ihre Kontur haengt nicht von der
    Zahnklasse ab (die Groesse dagegen schon, siehe test_snapping)."""
    a = PlanItem(kind=KIND_IMPLANTAT, x=0.5, y=0.5, width=0.03, height=0.08, fdi_tooth=17)
    b = PlanItem(kind=KIND_IMPLANTAT, x=0.5, y=0.5, width=0.03, height=0.08, fdi_tooth=11)
    assert (shapes.build_draw_ops(a, IMAGE_W, IMAGE_H)[0].points ==
            shapes.build_draw_ops(b, IMAGE_W, IMAGE_H)[0].points)


def test_aspect_ratio_differs_by_tooth_class():
    assert shapes.aspect_for(KIND_KRONE, 17) > shapes.aspect_for(KIND_KRONE, 11)
