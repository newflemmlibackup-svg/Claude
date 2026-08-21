"""Reine Geometrie-/Stil-Erzeugung fuer die Befund-Symbole.

Liefert fuer jede Planungsposition (PlanItem) eine Liste von `DrawOp`
("Zeichenoperationen") in absoluten Bildpixel-Koordinaten. Diese Liste wird
sowohl vom Tkinter-Canvas (zzgl. Zoom/Pan-Transformation) als auch vom
PIL-basierten Export (render.py) verwendet - so sehen Bildschirmdarstellung
und PDF/PNG-Export garantiert gleich aus.

Alle "normalen" (zahngebundenen bzw. frei platzierbaren) Symbole werden in
einem lokalen Einheitsquadrat [-0.5, 0.5] x [-0.5, 0.5] definiert und dann per
`_place()` skaliert (item.width/height), rotiert (item.rotation) und an
item.x/item.y verschoben. Die Bruecke ist ein Sonderfall (spannt zwei Punkte).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .models import (
    KIND_BRUECKE,
    KIND_EXTRAKTION,
    KIND_FEHLENDER_ZAHN,
    KIND_IMPLANTAT,
    KIND_KRONE,
    KIND_NICO_FDOK,
    KIND_TEILKRONE,
    KIND_WURZELBEHANDLUNG,
    KIND_LABELS,
)


@dataclass
class DrawOp:
    kind: str  # "polygon" | "line" | "text"
    points: list
    fill: str = ""
    outline: str = "#000000"
    width: float = 2.0
    dash: Optional[tuple] = None
    text: str = ""
    font_size: int = 12
    anchor: str = "center"


# ------------------------------------------------------------------- Farben
COLORS = {
    KIND_IMPLANTAT: {"fill": "#cfe0f7", "outline": "#2f5fa8", "text": "#1c3a66"},
    KIND_KRONE: {"fill": "#f3d67c", "outline": "#a9791a", "text": "#6b4c10"},
    KIND_TEILKRONE: {"fill": "#f8e9b8", "outline": "#a9791a", "text": "#6b4c10"},
    KIND_NICO_FDOK: {"fill": "", "outline": "#a4269c", "text": "#7a1c74"},
    KIND_EXTRAKTION: {"fill": "", "outline": "#c62828", "text": "#8f1c1c"},
    KIND_WURZELBEHANDLUNG: {"fill": "#e3d3f5", "outline": "#6a3fa0", "text": "#432a68"},
    KIND_FEHLENDER_ZAHN: {"fill": "", "outline": "#8a8a8a", "text": "#5a5a5a"},
    KIND_BRUECKE: {"fill": "#f3d67c", "outline": "#a9791a", "text": "#6b4c10"},
}

# Sinnvolle Default-Seitenverhaeltnisse (Breite:Hoehe), falls keine
# Kalibrierung vorliegt und die Groesse frei gewaehlt wird.
DEFAULT_ASPECT = {
    KIND_IMPLANTAT: 0.5,
    KIND_KRONE: 0.8,
    KIND_TEILKRONE: 0.8,
    KIND_NICO_FDOK: 1.3,
    KIND_EXTRAKTION: 0.9,
    KIND_WURZELBEHANDLUNG: 0.45,
    KIND_FEHLENDER_ZAHN: 0.8,
    KIND_BRUECKE: 1.0,
}


def legend_entries():
    """Liste von (kind, label, farbe) fuer Legenden in UI/Export."""
    return [(k, KIND_LABELS[k], COLORS[k]["outline"]) for k in COLORS]


def _rotate(dx: float, dy: float, theta: float) -> tuple:
    c, s = math.cos(theta), math.sin(theta)
    return dx * c - dy * s, dx * s + dy * c


def _place(local_points, cx, cy, w, h, theta) -> list:
    out = []
    for u, v in local_points:
        dx, dy = u * w, v * h
        rx, ry = _rotate(dx, dy, theta)
        out.append((cx + rx, cy + ry))
    return out


def _ellipse_points(n: int = 32) -> list:
    return [(0.5 * math.cos(t), 0.5 * math.sin(t)) for t in
            [2 * math.pi * i / n for i in range(n)]]


def _tooth_dome(width_frac: float = 1.0) -> list:
    """Kronenfoermige Kuppel (Kaufflaeche oben/aussen, Zahnhals unten/innen)
    im lokalen Einheitsquadrat. `width_frac` < 1 fuer eine schmalere
    (partielle) Variante."""
    w = width_frac * 0.5
    return [
        (-w, 0.15), (-w, -0.1), (-w * 0.7, -0.35), (-w * 0.25, -0.48),
        (0.0, -0.5), (w * 0.25, -0.48), (w * 0.7, -0.35), (w, -0.1),
        (w, 0.15), (w * 0.6, 0.4), (0.0, 0.5), (-w * 0.6, 0.4),
    ]


# ---------------------------------------------------------- Lokale Baupläne
def _local_ops_implantat():
    body = [
        (-0.16, -0.45), (0.16, -0.45), (0.16, 0.15), (0.0, 0.5), (-0.16, 0.15),
    ]
    head = [(-0.24, -0.5), (0.24, -0.5), (0.24, -0.42), (-0.24, -0.42)]
    threads = [
        [(-0.16, v), (0.16, v)] for v in (-0.25, -0.05, 0.0)
    ] + [
        [(-0.13, 0.08), (0.13, 0.08)],
    ]
    c = COLORS[KIND_IMPLANTAT]
    ops = [
        ("polygon", body, c["fill"], c["outline"], 2.0, None),
        ("polygon", head, c["outline"], c["outline"], 1.0, None),
    ]
    for seg in threads:
        ops.append(("line", seg, "", c["outline"], 1.5, None))
    return ops


def _local_ops_krone():
    c = COLORS[KIND_KRONE]
    return [("polygon", _tooth_dome(1.0), c["fill"], c["outline"], 2.0, None)]


def _local_ops_teilkrone():
    c = COLORS[KIND_TEILKRONE]
    return [("polygon", _tooth_dome(0.85), c["fill"], c["outline"], 2.0, (5, 3))]


def _local_ops_nico_fdok():
    c = COLORS[KIND_NICO_FDOK]
    ops = [("polygon", _ellipse_points(28), c["fill"], c["outline"], 2.0, (4, 3))]
    ops.append(("text", [(0.0, 0.72)], "", "", 0, None, "NICO/FDOK", 11, "center"))
    return ops


def _local_ops_extraktion():
    c = COLORS[KIND_EXTRAKTION]
    return [
        ("line", [(-0.45, -0.45), (0.45, 0.45)], "", c["outline"], 4.0, None),
        ("line", [(-0.45, 0.45), (0.45, -0.45)], "", c["outline"], 4.0, None),
    ]


def _local_ops_wurzelbehandlung():
    c = COLORS[KIND_WURZELBEHANDLUNG]
    root = [
        (-0.18, -0.5), (0.18, -0.5), (0.12, 0.1), (0.0, 0.5), (-0.12, 0.1),
    ]
    return [
        ("polygon", root, "", c["outline"], 2.0, None),
        ("line", [(0.0, -0.45), (0.0, 0.45)], "", c["outline"], 3.0, None),
    ]


def _local_ops_fehlender_zahn():
    c = COLORS[KIND_FEHLENDER_ZAHN]
    return [
        ("polygon", _tooth_dome(1.0), "", c["outline"], 2.0, (3, 4)),
        ("line", [(-0.5, 0.55), (0.5, 0.55)], "", c["outline"], 1.5, (2, 3)),
    ]


_LOCAL_BUILDERS = {
    KIND_IMPLANTAT: _local_ops_implantat,
    KIND_KRONE: _local_ops_krone,
    KIND_TEILKRONE: _local_ops_teilkrone,
    KIND_NICO_FDOK: _local_ops_nico_fdok,
    KIND_EXTRAKTION: _local_ops_extraktion,
    KIND_WURZELBEHANDLUNG: _local_ops_wurzelbehandlung,
    KIND_FEHLENDER_ZAHN: _local_ops_fehlender_zahn,
}


def _font_size_for(w_px: float, h_px: float) -> int:
    size = int(round(math.sqrt(max(w_px, 1) * max(h_px, 1)) * 0.22))
    return max(8, min(size, 48))


def _build_simple(item, image_w: int, image_h: int) -> list:
    cx, cy = item.x * image_w, item.y * image_h
    w, h = item.width * image_w, item.height * image_h
    theta = math.radians(item.rotation)
    ops = []
    for local_op in _LOCAL_BUILDERS[item.kind]():
        op_kind, local_pts, fill, outline, lw, dash, *rest = local_op
        pts = _place(local_pts, cx, cy, w, h, theta)
        if op_kind == "text":
            text, font_size, anchor = rest
            ops.append(DrawOp("text", pts, "", "", 0, None, text,
                               _font_size_for(w, h) if font_size is None else font_size, anchor))
        else:
            ops.append(DrawOp(op_kind, pts, fill, outline, lw, dash))
    return ops


def _build_bruecke(item, image_w: int, image_h: int) -> list:
    c = COLORS[KIND_BRUECKE]
    x0, y0 = item.x * image_w, item.y * image_h
    ex = item.end_x if item.end_x is not None else item.x + item.width
    ey = item.end_y if item.end_y is not None else item.y
    x1, y1 = ex * image_w, ey * image_h

    thickness = max(item.height * image_h, 4.0)
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length  # Normalenvektor

    half = thickness / 2.0
    bar = [
        (x0 + nx * half, y0 + ny * half),
        (x1 + nx * half, y1 + ny * half),
        (x1 - nx * half, y1 - ny * half),
        (x0 - nx * half, y0 - ny * half),
    ]
    ops = [DrawOp("polygon", bar, c["fill"], c["outline"], 2.0, None)]

    # Kleine Querstriche an jeder ueberspannten Zahnposition (Pfeiler/Glieder).
    n_teeth = len(item.bridge_teeth) if item.bridge_teeth else 2
    n_teeth = max(n_teeth, 2)
    r = thickness * 0.6
    for i in range(n_teeth):
        t = i / (n_teeth - 1)
        px, py = x0 + dx * t, y0 + dy * t
        ops.append(DrawOp(
            "line",
            [(px + nx * r, py + ny * r), (px - nx * r, py - ny * r)],
            "", c["outline"], 2.5, None,
        ))
    return ops


def transform_local_points(local_points, item, image_w: int, image_h: int) -> list:
    """Oeffentlicher Zugriff auf die Lokal->Bildpixel-Transformation (Skalierung
    mit item.width/height, Rotation mit item.rotation, Verschiebung nach
    item.x/y). Wird von der Canvas-Ansicht fuer Auswahlrahmen/Greifpunkte
    verwendet, die exakt zur gezeichneten Symbolgeometrie passen muessen."""
    cx, cy = item.x * image_w, item.y * image_h
    w, h = item.width * image_w, item.height * image_h
    theta = math.radians(item.rotation)
    return _place(local_points, cx, cy, w, h, theta)


def build_draw_ops(item, image_w: int, image_h: int) -> list:
    """Liefert die Liste der DrawOps (absolute Pixelkoordinaten) fuer `item`."""
    if item.kind == KIND_BRUECKE:
        return _build_bruecke(item, image_w, image_h)
    return _build_simple(item, image_w, image_h)


def bounding_box(item, image_w: int, image_h: int) -> tuple:
    """(x0, y0, x1, y1) in Pixeln - fuer Auswahlrahmen/Handles."""
    if item.kind == KIND_BRUECKE:
        pts = []
        for op in build_draw_ops(item, image_w, image_h):
            pts.extend(op.points)
    else:
        cx, cy = item.x * image_w, item.y * image_h
        w, h = item.width * image_w, item.height * image_h
        theta = math.radians(item.rotation)
        corners = [(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)]
        pts = _place(corners, cx, cy, w, h, theta)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)
