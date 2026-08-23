"""Zuordnung von Symbolen zu kalibrierten FDI-Zahnpositionen.

Bewusst frei von Tkinter, damit die Logik unabhaengig von Zoomstufe und
Fenstergroesse getestet werden kann. Gerechnet wird in Bildpixeln (Anteile
mal Bildgroesse), weil Bilder selten quadratisch sind und Abstaende in reinen
Anteilswerten sonst horizontal/vertikal unterschiedlich gewichtet waeren.

Zwei Radien, jeweils als Vielfaches des lokalen Zahnabstands:

* ASSIGN_FACTOR  - bis hierhin bekommt ein Symbol die Zahnnummer zugewiesen.
                   Grosszuegig, damit die Zuordnung praktisch immer greift,
                   wenn ueberhaupt im Bereich des Zahnbogens abgelegt wird.
* MAGNET_FACTOR  - bis hierhin rastet zusaetzlich die Position auf den Zahn
                   ein. Eng, damit sich Symbole trotzdem frei feinjustieren
                   lassen.
"""
from __future__ import annotations

import math
from typing import Optional

from .fdi import row_neighbors
from .models import KIND_IMPLANTAT
from .shapes import aspect_for

# Eine volle Zahnbreite: grosszuegig genug, dass die Zuordnung beim Ablegen
# im Zahnbogen praktisch immer greift, aber eng genug, dass der Spalt
# zwischen Ober- und Unterkiefer nicht mehr faelschlich zugeordnet wird.
ASSIGN_FACTOR = 1.0
MAGNET_FACTOR = 0.45

# Fallback, wenn sich kein Nachbarabstand bestimmen laesst (z. B. nur ein
# einziger kalibrierter Punkt): Anteil der Bilddiagonale.
FALLBACK_SPACING_FRACTION = 0.035

# Anteil des Zahnabstands, den eine Krone in der Breite einnimmt. Kronen
# reichen mesio-distal fast bis an die Nachbarzaehne heran.
CROWN_WIDTH_RATIO = 0.92
IMPLANT_WIDTH_RATIO = 0.55


def _px(point, image_w: int, image_h: int) -> tuple:
    return point[0] * image_w, point[1] * image_h


def local_spacing_px(calibration_points: dict, tooth: int, image_w: int, image_h: int) -> float:
    """Abstand des Zahns zu seinem naechsten Nachbarn im selben Kieferbogen,
    in Bildpixeln. Dient als Massstab fuer Snap-Radius und Symbolgroesse."""
    if tooth not in calibration_points:
        return FALLBACK_SPACING_FRACTION * math.hypot(image_w, image_h)

    own = _px(calibration_points[tooth], image_w, image_h)
    distances = []
    for neighbor in row_neighbors(tooth):
        if neighbor is None or neighbor not in calibration_points:
            continue
        other = _px(calibration_points[neighbor], image_w, image_h)
        distances.append(math.dist(own, other))

    if not distances:
        return FALLBACK_SPACING_FRACTION * math.hypot(image_w, image_h)
    return min(distances)


def nearest_tooth(calibration_points: dict, fx: float, fy: float,
                   image_w: int, image_h: int,
                   *, factor: float = ASSIGN_FACTOR) -> Optional[int]:
    """FDI-Nummer des naechstgelegenen kalibrierten Zahns, sofern die Position
    innerhalb von `factor` x lokalem Zahnabstand liegt - sonst None."""
    if not calibration_points:
        return None

    target = (fx * image_w, fy * image_h)
    best_tooth = None
    best_distance = None
    for tooth, point in calibration_points.items():
        distance = math.dist(target, _px(point, image_w, image_h))
        if best_distance is None or distance < best_distance:
            best_tooth, best_distance = tooth, distance

    if best_tooth is None:
        return None
    allowed = local_spacing_px(calibration_points, best_tooth, image_w, image_h) * factor
    return best_tooth if best_distance <= allowed else None


def snap_position(calibration_points: dict, fx: float, fy: float,
                   image_w: int, image_h: int) -> tuple:
    """(x, y, zahn_oder_None): rastet die Position magnetisch auf den
    naechsten Zahn ein, wenn sie nah genug liegt, und liefert zusaetzlich die
    (grosszuegiger vergebene) Zahnzuordnung."""
    tooth = nearest_tooth(calibration_points, fx, fy, image_w, image_h)
    if tooth is None:
        return fx, fy, None

    point = calibration_points[tooth]
    distance = math.dist((fx * image_w, fy * image_h), _px(point, image_w, image_h))
    magnet_radius = local_spacing_px(calibration_points, tooth, image_w, image_h) * MAGNET_FACTOR
    if distance <= magnet_radius:
        return point[0], point[1], tooth
    return fx, fy, tooth


def fit_box_for_tooth(kind: str, tooth: Optional[int], calibration_points: dict,
                       image_w: int, image_h: int,
                       *, fallback_width_fraction: float = 0.045) -> tuple:
    """(breite, hoehe) als Anteil der Bildbreite/-hoehe, passend zur Groesse
    des kalibrierten Zahns. Ohne Kalibrierung greift die Fallback-Breite."""
    if tooth is not None and tooth in calibration_points:
        spacing = local_spacing_px(calibration_points, tooth, image_w, image_h)
        ratio = IMPLANT_WIDTH_RATIO if kind == KIND_IMPLANTAT else CROWN_WIDTH_RATIO
        width_px = spacing * ratio
    else:
        width_px = fallback_width_fraction * image_w

    aspect = aspect_for(kind, tooth)
    height_px = width_px / aspect if aspect else width_px

    return width_px / image_w, height_px / image_h
