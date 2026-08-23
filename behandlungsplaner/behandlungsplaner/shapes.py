"""Geometrie- und Stilerzeugung fuer die Befund-Symbole.

Liefert fuer jede Planungsposition (PlanItem) eine Liste von `DrawOp`
("Zeichenoperationen") in absoluten Bildpixel-Koordinaten. Diese Liste wird
sowohl vom Tkinter-Canvas (zzgl. Zoom/Pan-Transformation) als auch vom
PIL-basierten Export (render.py) verwendet - so sehen Bildschirmdarstellung
und PDF/PNG-Export garantiert gleich aus.

Die Symbole werden im lokalen Einheitsquadrat [-0.5, 0.5] x [-0.5, 0.5]
definiert und dann per `_place()` skaliert (item.width/height), rotiert
(item.rotation) und an item.x/item.y verschoben. Die Bruecke ist ein
Sonderfall (spannt zwei Punkte).

Zahngebundene Symbole (Krone, Teilkrone, Extraktion, Wurzelbehandlung,
fehlender Zahn) richten ihre Kontur nach der FDI-Zahnklasse: ein Molar
bekommt eine breite Kaufflaeche mit vier Hoeckern, ein Schneidezahn eine
schmale flache Schneide. Zusaetzlich wird die Kaufflaeche automatisch zum
Gegenkiefer hin ausgerichtet (Oberkiefer nach unten, Unterkiefer nach oben),
ohne dafuer `item.rotation` zu verbrauchen.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from . import tooth_anatomy as anat
from .fdi import fdi_arch
from .models import (
    KIND_BRUECKE,
    KIND_EXTRAKTION,
    KIND_FEHLENDER_ZAHN,
    KIND_IMPLANTAT,
    KIND_KRONE,
    KIND_LABELS,
    KIND_NICO_FDOK,
    KIND_TEILKRONE,
    KIND_WURZELBEHANDLUNG,
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

# Befundarten, deren Kontur sich nach der Zahnklasse richtet.
TOOTH_SHAPED_KINDS = {
    KIND_KRONE,
    KIND_TEILKRONE,
    KIND_EXTRAKTION,
    KIND_WURZELBEHANDLUNG,
    KIND_FEHLENDER_ZAHN,
}

# Symbole, die den ganzen Zahn (Krone + Wurzel) darstellen - im Gegensatz zu
# reinen Kronenversorgungen.
FULL_TOOTH_KINDS = {KIND_EXTRAKTION, KIND_WURZELBEHANDLUNG, KIND_FEHLENDER_ZAHN}

# Fallback-Seitenverhaeltnisse (Breite:Hoehe) fuer nicht zahngebundene Symbole.
DEFAULT_ASPECT = {
    KIND_IMPLANTAT: 0.5,
    KIND_KRONE: 1.15,
    KIND_TEILKRONE: 1.15,
    KIND_NICO_FDOK: 1.3,
    KIND_EXTRAKTION: 0.85,
    KIND_WURZELBEHANDLUNG: 0.85,
    KIND_FEHLENDER_ZAHN: 0.85,
    KIND_BRUECKE: 1.0,
}


def aspect_for(kind: str, fdi_tooth=None) -> float:
    """Sinnvolles Breite:Hoehe-Verhaeltnis, abhaengig von Befundart und - bei
    zahngebundenen Symbolen - von der Zahnklasse."""
    if kind in TOOTH_SHAPED_KINDS:
        tooth_class = anat.tooth_class_for(fdi_tooth)
        table = anat.FULL_TOOTH_ASPECT if kind in FULL_TOOTH_KINDS else anat.CROWN_ASPECT
        return table[tooth_class]
    return DEFAULT_ASPECT.get(kind, 0.8)


def legend_entries():
    """Liste von (kind, label, farbe) fuer Legenden in UI/Export."""
    return [(k, KIND_LABELS[k], COLORS[k]["outline"]) for k in COLORS]


def arch_flip(fdi_tooth) -> float:
    """+1 oder -1: spiegelt die lokale y-Achse, damit die Kaufflaeche bei
    Oberkieferzaehnen nach unten und bei Unterkieferzaehnen nach oben zeigt.

    Ohne Zahnzuordnung wird die Unterkiefer-Ausrichtung (Kauflaeche oben)
    als neutraler Default verwendet - so wie die Symbole auch in der Palette
    dargestellt sind.
    """
    if fdi_tooth is None:
        return 1.0
    return -1.0 if fdi_arch(fdi_tooth) == "oben" else 1.0


def _rotate(dx: float, dy: float, theta: float) -> tuple:
    c, s = math.cos(theta), math.sin(theta)
    return dx * c - dy * s, dx * s + dy * c


def _place(local_points, cx, cy, w, h, theta, flip=1.0) -> list:
    out = []
    for u, v in local_points:
        dx, dy = u * w, v * h * flip
        rx, ry = _rotate(dx, dy, theta)
        out.append((cx + rx, cy + ry))
    return out


def _ellipse_points(n: int = 32) -> list:
    return [(0.5 * math.cos(t), 0.5 * math.sin(t)) for t in
            [2 * math.pi * i / n for i in range(n)]]


def _scale_y(points, factor, offset=0.0):
    return [(x, y * factor + offset) for x, y in points]


def _scale_x(points, factor):
    return [(x * factor, y) for x, y in points]


# ---------------------------------------------------------- Lokale Baupläne
def _local_ops_implantat(_tooth_class):
    c = COLORS[KIND_IMPLANTAT]
    # Enossaler Anteil: konisch, mit angedeutetem Gewinde; Aufbau/Schulter oben.
    body = [
        (-0.17, -0.42), (0.17, -0.42), (0.15, 0.10), (0.0, 0.5), (-0.15, 0.10),
    ]
    shoulder = [(-0.25, -0.5), (0.25, -0.5), (0.23, -0.40), (-0.23, -0.40)]
    ops = [
        DrawOp("polygon", body, c["fill"], c["outline"], 2.0),
        DrawOp("polygon", shoulder, c["fill"], c["outline"], 1.6),
    ]
    for v in (-0.28, -0.14, 0.0, 0.14):
        # Gewindegaenge folgen der konischen Verjuengung.
        t = (v + 0.42) / 0.92
        half = 0.17 - t * 0.06
        ops.append(DrawOp("line", [(-half, v), (half, v)], "", c["outline"], 1.4))
    return ops


def _local_ops_krone(tooth_class):
    c = COLORS[KIND_KRONE]
    return [DrawOp("polygon", anat.crown_profile(tooth_class), c["fill"], c["outline"], 2.2)]


def _local_ops_teilkrone(tooth_class):
    c = COLORS[KIND_TEILKRONE]
    profile = anat.crown_profile(tooth_class)
    ops = [DrawOp("polygon", profile, c["fill"], c["outline"], 2.0, (5, 3))]
    # Praeparationsgrenze andeuten: Teilkrone bedeckt nur den okklusalen Teil.
    hw = anat.CROWN_HALF_WIDTH[tooth_class]
    ops.append(DrawOp("line", [(-hw * 0.94, 0.06), (hw * 0.94, 0.06)], "", c["outline"], 1.6, (4, 3)))
    return ops


def _local_ops_nico_fdok(_tooth_class):
    c = COLORS[KIND_NICO_FDOK]
    return [
        DrawOp("polygon", _ellipse_points(28), c["fill"], c["outline"], 2.0, (4, 3)),
        # Beschriftung mittig IN der Ellipse - ausserhalb wuerde sie bei
        # grossen Symbolen ueber die Kontur hinauslaufen.
        DrawOp("text", [(0.0, 0.0)], "", "", 0, None, "NICO/FDOK", 11, "center"),
    ]


def _local_ops_extraktion(tooth_class):
    c = COLORS[KIND_EXTRAKTION]
    crown, roots = anat.full_tooth_profile(tooth_class)
    ops = [DrawOp("polygon", crown, "", c["outline"], 1.6, (3, 3))]
    for root in roots:
        ops.append(DrawOp("polygon", root, "", c["outline"], 1.6, (3, 3)))
    # Deutliches Kreuz ueber dem gesamten Zahn.
    ops += [
        DrawOp("line", [(-0.44, -0.44), (0.44, 0.44)], "", c["outline"], 4.0),
        DrawOp("line", [(-0.44, 0.44), (0.44, -0.44)], "", c["outline"], 4.0),
    ]
    return ops


def _local_ops_wurzelbehandlung(tooth_class):
    c = COLORS[KIND_WURZELBEHANDLUNG]
    crown, roots = anat.full_tooth_profile(tooth_class)
    share = anat.CROWN_HEIGHT_SHARE[tooth_class]
    neck_y = -0.5 + share

    ops = [DrawOp("polygon", crown, c["fill"], c["outline"], 1.8)]
    for root in roots:
        ops.append(DrawOp("polygon", root, c["fill"], c["outline"], 1.8))
    # Wurzelfuellung: kraeftige Linie je Kanal.
    for line in anat.root_canal_lines(tooth_class, top_y=neck_y - 0.02, bottom_y=0.5):
        ops.append(DrawOp("line", line, "", c["outline"], 3.2))
    return ops


def _local_ops_fehlender_zahn(tooth_class):
    c = COLORS[KIND_FEHLENDER_ZAHN]
    crown, roots = anat.full_tooth_profile(tooth_class)
    ops = [DrawOp("polygon", crown, "", c["outline"], 1.8, (3, 4))]
    for root in roots:
        ops.append(DrawOp("polygon", root, "", c["outline"], 1.8, (3, 4)))
    return ops


_LOCAL_BUILDERS = {
    KIND_IMPLANTAT: _local_ops_implantat,
    KIND_KRONE: _local_ops_krone,
    KIND_TEILKRONE: _local_ops_teilkrone,
    KIND_NICO_FDOK: _local_ops_nico_fdok,
    KIND_EXTRAKTION: _local_ops_extraktion,
    KIND_WURZELBEHANDLUNG: _local_ops_wurzelbehandlung,
    KIND_FEHLENDER_ZAHN: _local_ops_fehlender_zahn,
}


def local_draw_ops(kind: str, fdi_tooth=None) -> list:
    """DrawOps im lokalen Einheitsquadrat - Basis fuer Canvas, Export sowie
    die Vorschau-Icons in der Palette."""
    tooth_class = anat.tooth_class_for(fdi_tooth)
    return _LOCAL_BUILDERS[kind](tooth_class)


def _font_size_for(w_px: float, h_px: float, text: str) -> int:
    """Schriftgroesse so waehlen, dass die Beschriftung ungefaehr in die
    Symbolbreite passt - sonst laeuft z. B. 'NICO/FDOK' bei grossen Symbolen
    weit ueber die Kontur hinaus."""
    if not text:
        return 10
    # Grobe Faustregel: mittlere Zeichenbreite ~0.6 der Schriftgroesse.
    fit_to_width = (max(w_px, 1) * 1.25) / (len(text) * 0.6)
    fit_to_height = max(h_px, 1) * 0.22
    return max(8, min(int(round(min(fit_to_width, fit_to_height))), 40))


def _build_simple(item, image_w: int, image_h: int) -> list:
    cx, cy = item.x * image_w, item.y * image_h
    w, h = item.width * image_w, item.height * image_h
    theta = math.radians(item.rotation)
    flip = arch_flip(item.fdi_tooth) if item.kind in TOOTH_SHAPED_KINDS else 1.0

    ops = []
    for local_op in local_draw_ops(item.kind, item.fdi_tooth):
        pts = _place(local_op.points, cx, cy, w, h, theta, flip)
        if local_op.kind == "text":
            ops.append(DrawOp("text", pts, "", "", 0, None, local_op.text,
                              _font_size_for(w, h, local_op.text), local_op.anchor))
        else:
            ops.append(DrawOp(local_op.kind, pts, local_op.fill, local_op.outline,
                              local_op.width, local_op.dash))
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


def transform_local_points(local_points, item, image_w: int, image_h: int,
                            *, apply_flip: bool = False) -> list:
    """Oeffentlicher Zugriff auf die Lokal->Bildpixel-Transformation (Skalierung
    mit item.width/height, Rotation mit item.rotation, Verschiebung nach
    item.x/y). Wird von der Canvas-Ansicht fuer Auswahlrahmen/Greifpunkte
    verwendet, die exakt zur gezeichneten Symbolgeometrie passen muessen.

    `apply_flip` bezieht zusaetzlich die Ober-/Unterkiefer-Spiegelung ein -
    fuer Greifpunkte i.d.R. unerwuenscht, damit der Drehgriff immer an
    derselben Stelle relativ zum Nutzerblick sitzt.
    """
    cx, cy = item.x * image_w, item.y * image_h
    w, h = item.width * image_w, item.height * image_h
    theta = math.radians(item.rotation)
    flip = arch_flip(item.fdi_tooth) if (apply_flip and item.kind in TOOTH_SHAPED_KINDS) else 1.0
    return _place(local_points, cx, cy, w, h, theta, flip)


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
        corners = [(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)]
        pts = transform_local_points(corners, item, image_w, image_h)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)
