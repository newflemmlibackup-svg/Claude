"""FDI-Zahnschema (ISO 3950): Quadranten 1-4, je 8 Zaehne (bleibendes Gebiss).

11-18 = oben rechts (Q1), 21-28 = oben links (Q2),
31-38 = unten links (Q3), 41-48 = unten rechts (Q4).

Auf einem OPG in radiologischer Standardansicht (Patient blickt den Betrachter
an) erscheint die rechte Patientenseite links im Bild. Reihenfolge links nach
rechts im Bild:
  oben:  18 17 16 15 14 13 12 11 | 21 22 23 24 25 26 27 28
  unten: 48 47 46 45 44 43 42 41 | 31 32 33 34 35 36 37 38
"""
from __future__ import annotations

UPPER_ROW_LEFT_TO_RIGHT = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
LOWER_ROW_LEFT_TO_RIGHT = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]

ALL_FDI_TEETH = UPPER_ROW_LEFT_TO_RIGHT + LOWER_ROW_LEFT_TO_RIGHT

_TOOTH_CLASS_BY_INDEX = {
    1: "schneidezahn",
    2: "schneidezahn",
    3: "eckzahn",
    4: "praemolar",
    5: "praemolar",
    6: "molar",
    7: "molar",
    8: "molar",
}


def is_valid_fdi(tooth: int) -> bool:
    if not isinstance(tooth, int):
        return False
    quadrant, index = divmod(tooth, 10)
    return quadrant in (1, 2, 3, 4) and index in range(1, 9)


def fdi_quadrant(tooth: int) -> int:
    if not is_valid_fdi(tooth):
        raise ValueError(f"Ungueltige FDI-Zahnnummer: {tooth}")
    return tooth // 10


def fdi_tooth_index(tooth: int) -> int:
    if not is_valid_fdi(tooth):
        raise ValueError(f"Ungueltige FDI-Zahnnummer: {tooth}")
    return tooth % 10


def fdi_arch(tooth: int) -> str:
    """'oben' oder 'unten'."""
    return "oben" if fdi_quadrant(tooth) in (1, 2) else "unten"


def fdi_side(tooth: int) -> str:
    """'rechts' oder 'links' (aus Patientensicht)."""
    return "rechts" if fdi_quadrant(tooth) in (1, 4) else "links"


def fdi_tooth_class(tooth: int) -> str:
    """Grobe Zahnklasse (Schneidezahn/Eckzahn/Praemolar/Molar) - dient als
    Fallback fuer eine plausible Standardgroesse/-form, wenn keine Kalibrierung
    vorliegt."""
    return _TOOTH_CLASS_BY_INDEX[fdi_tooth_index(tooth)]


def fdi_label(tooth: int) -> str:
    return f"{tooth} ({fdi_arch(tooth)} {fdi_side(tooth)}, {fdi_tooth_class(tooth)})"


def default_row_position(tooth: int) -> tuple:
    """Index (0..15) und Zeile ('oben'/'unten') in der Standard-Bildreihenfolge
    links->rechts, fuer die Default-Platzierung des Kalibrierrasters."""
    if tooth in UPPER_ROW_LEFT_TO_RIGHT:
        return UPPER_ROW_LEFT_TO_RIGHT.index(tooth), "oben"
    if tooth in LOWER_ROW_LEFT_TO_RIGHT:
        return LOWER_ROW_LEFT_TO_RIGHT.index(tooth), "unten"
    raise ValueError(f"Ungueltige FDI-Zahnnummer: {tooth}")


def row_neighbors(tooth: int) -> tuple:
    """(linker_nachbar, rechter_nachbar) in derselben Bildzeile, oder None an
    den Bogenenden."""
    idx, row = default_row_position(tooth)
    row_list = UPPER_ROW_LEFT_TO_RIGHT if row == "oben" else LOWER_ROW_LEFT_TO_RIGHT
    left = row_list[idx - 1] if idx > 0 else None
    right = row_list[idx + 1] if idx < len(row_list) - 1 else None
    return left, right


def teeth_between(tooth_a: int, tooth_b: int) -> list:
    """Liste der FDI-Zahnnummern zwischen (und einschliesslich) `tooth_a` und
    `tooth_b`, sofern beide in derselben Bildzeile liegen (sonst [tooth_a,
    tooth_b])."""
    idx_a, row_a = default_row_position(tooth_a)
    idx_b, row_b = default_row_position(tooth_b)
    if row_a != row_b:
        return [tooth_a, tooth_b]
    row_list = UPPER_ROW_LEFT_TO_RIGHT if row_a == "oben" else LOWER_ROW_LEFT_TO_RIGHT
    lo, hi = min(idx_a, idx_b), max(idx_a, idx_b)
    return row_list[lo:hi + 1]


def default_calibration_layout() -> dict:
    """Plausible Standard-Ausgangspositionen (Anteil der Bildbreite/-hoehe)
    fuer alle 32 FDI-Zaehne entlang zweier Bogenkurven, wie sie auf einem
    typischen OPG in etwa erscheinen. Rein als Startpunkt fuer die manuelle
    Kalibrierung gedacht - die Kurve muss vom Anwender an das echte Bild
    angepasst werden.
    """
    margin = 0.03
    span = 1.0 - 2 * margin
    upper_base, upper_amp = 0.22, 0.16
    lower_base, lower_amp = 0.80, -0.16

    layout = {}
    for i, tooth in enumerate(UPPER_ROW_LEFT_TO_RIGHT):
        t = i / (len(UPPER_ROW_LEFT_TO_RIGHT) - 1)
        x = margin + t * span
        y = upper_base + upper_amp * (1 - (2 * t - 1) ** 2)
        layout[tooth] = (x, y)
    for i, tooth in enumerate(LOWER_ROW_LEFT_TO_RIGHT):
        t = i / (len(LOWER_ROW_LEFT_TO_RIGHT) - 1)
        x = margin + t * span
        y = lower_base + lower_amp * (1 - (2 * t - 1) ** 2)
        layout[tooth] = (x, y)
    return layout
