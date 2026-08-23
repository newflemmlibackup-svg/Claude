"""Anatomische Konturen der Zahnklassen (Molar, Praemolar, Eckzahn,
Schneidezahn) als normierte Polygone.

Alle Profile leben im lokalen Einheitsquadrat [-0.5, 0.5] x [-0.5, 0.5]:

    y = -0.5  ... okklusal / inzisal (Kaufflaeche bzw. Schneide)
    y = +0.5  ... apikal (Wurzelspitze) bzw. zervikal (Zahnhals) bei
                  reinen Kronenprofilen

Die Ausrichtung im Bild (Oberkiefer = Kaufflaeche zeigt nach unten,
Unterkiefer = nach oben) wird NICHT hier, sondern beim Zeichnen ueber ein
Spiegeln der y-Achse erzeugt (siehe shapes.arch_flip). Dadurch bleibt
`PlanItem.rotation` ausschliesslich eine bewusste Nutzeranpassung fuer
gekippte Zaehne.
"""
from __future__ import annotations

from .fdi import fdi_tooth_class

# Zahnklasse -> Anzahl Hoecker auf der Kaufflaeche
CUSP_COUNT = {
    "molar": 4,
    "praemolar": 2,
    "eckzahn": 1,
    "schneidezahn": 0,  # durchgehende Schneidekante statt Hoecker
}

# Zahnklasse -> Anzahl Wurzeln
ROOT_COUNT = {
    "molar": 2,        # vereinfacht: mesial + distal (OK-Molaren real 3)
    "praemolar": 1,
    "eckzahn": 1,
    "schneidezahn": 1,
}

# Zahnklasse -> halbe Kronenbreite im lokalen Einheitsquadrat.
# Molaren sind breit, Schneidezaehne schmal - das ist der sichtbarste
# Unterschied auf dem OPG.
CROWN_HALF_WIDTH = {
    "molar": 0.50,
    "praemolar": 0.38,
    "eckzahn": 0.34,
    "schneidezahn": 0.31,
}

# Zahnklasse -> Breite:Hoehe des umschliessenden Rechtecks. Steuert die
# automatische Vorskalierung beim Platzieren auf einen kalibrierten Zahn.
CROWN_ASPECT = {
    "molar": 1.15,
    "praemolar": 0.85,
    "eckzahn": 0.72,
    "schneidezahn": 0.78,
}

FULL_TOOTH_ASPECT = {
    "molar": 0.85,
    "praemolar": 0.50,
    "eckzahn": 0.42,
    "schneidezahn": 0.46,
}

# Anteil der Gesamthoehe, den die Krone eines vollstaendigen Zahns einnimmt.
CROWN_HEIGHT_SHARE = {
    "molar": 0.46,
    "praemolar": 0.40,
    "eckzahn": 0.34,
    "schneidezahn": 0.38,
}

ALL_TOOTH_CLASSES = ("schneidezahn", "eckzahn", "praemolar", "molar")

DEFAULT_TOOTH_CLASS = "molar"


def tooth_class_for(fdi_tooth) -> str:
    """Zahnklasse zu einer FDI-Nummer; ohne Zuordnung ein neutraler Default."""
    if fdi_tooth is None:
        return DEFAULT_TOOTH_CLASS
    return fdi_tooth_class(fdi_tooth)


# Hoeckerform: Exponent auf die Kosinuswelle. < 1 ergibt breite, abgerundete
# Hoecker (Seitenzaehne), > 1 eine schlankere Spitze (Eckzahn).
_CUSP_SHARPNESS = {
    "molar": 0.72,
    "praemolar": 0.78,
    "eckzahn": 1.5,
}

_SAMPLES_PER_CUSP = 9


def occlusal_edge(tooth_class: str, half_width: float, tip_y: float, valley_y: float) -> list:
    """Kaufflaechenkontur von mesial nach distal (links nach rechts im lokalen
    Koordinatensystem), mit klassenspezifischer Hoeckerzahl.

    Die Hoecker werden als abgetastete Kosinuswelle erzeugt, damit sie rund
    wie echte Hoecker wirken und nicht wie Saegezaehne.
    """
    import math

    cusps = CUSP_COUNT[tooth_class]

    if cusps == 0:
        # Schneidezahn: gerade Schneidekante mit leicht gebrochenen Ecken.
        return [
            (-half_width * 0.86, valley_y),
            (-half_width * 0.74, tip_y),
            (half_width * 0.74, tip_y),
            (half_width * 0.86, valley_y),
        ]

    sharpness = _CUSP_SHARPNESS[tooth_class]
    span = half_width * 0.88
    amplitude = valley_y - tip_y

    points = [(-half_width * 0.94, valley_y)]
    total_samples = cusps * _SAMPLES_PER_CUSP
    for i in range(total_samples + 1):
        t = i / total_samples                      # 0..1 ueber die Kaufflaeche
        x = (-1.0 + 2.0 * t) * span
        # Eine volle Kosinusperiode je Hoecker. Ohne Phasenverschiebung liegen
        # die Maxima bei t=(i+0.5)/n, also in den Hoeckermitten, und die
        # Minima (Fissuren) an den Segmentgrenzen einschliesslich der Raender.
        wave = 0.5 - 0.5 * math.cos(2 * math.pi * t * cusps)
        points.append((x, valley_y - amplitude * (wave ** sharpness)))
    points.append((half_width * 0.94, valley_y))
    return points


# Seitenkontur der Krone von der Kaufflaeche (t=0) zum Zahnhals (t=1):
# (y, relative_breite). Der groesste Umfang liegt im okklusalen Drittel, zum
# Zahnhals hin laeuft die Krone deutlich schmaler zu.
_CROWN_WALL = [
    (-0.30, 1.00),
    (-0.12, 0.99),
    (0.06, 0.95),
    (0.22, 0.88),
    (0.36, 0.80),
    (0.46, 0.73),
    (0.50, 0.70),
]


def crown_profile(tooth_class: str) -> list:
    """Reine Kronenkontur (ohne Wurzel), fuellt das lokale Einheitsquadrat.

    Kaufflaeche bei y = -0.5, Zahnhals bei y = +0.5.
    """
    hw = CROWN_HALF_WIDTH[tooth_class]
    tip_y = -0.5
    valley_y = -0.5 + (0.13 if tooth_class in ("molar", "praemolar") else 0.08)

    points = list(occlusal_edge(tooth_class, hw, tip_y, valley_y))

    # Distale Wand nach unten, dann Zahnhals, dann mesiale Wand zurueck hoch.
    points += [(hw * rel, y) for y, rel in _CROWN_WALL]
    points += [(-hw * rel, y) for y, rel in reversed(_CROWN_WALL)]
    return points


def root_profiles(tooth_class: str, *, top_y: float = 0.0, bottom_y: float = 0.5) -> list:
    """Wurzelkonturen zwischen `top_y` (Zahnhals) und `bottom_y` (Apex).

    Liefert eine Liste von Polygonen - Molaren haben zwei divergierende
    Wurzeln, alle anderen Klassen eine.
    """
    hw = CROWN_HALF_WIDTH[tooth_class]
    height = bottom_y - top_y
    roots = ROOT_COUNT[tooth_class]

    if roots == 1:
        half = hw * 0.40
        return [[
            (-half, top_y),
            (half, top_y),
            (half * 0.80, top_y + height * 0.40),
            (half * 0.50, top_y + height * 0.72),
            (0.0, bottom_y),
            (-half * 0.50, top_y + height * 0.72),
            (-half * 0.80, top_y + height * 0.40),
        ]]

    # Zwei Wurzeln, die nach apikal leicht auseinanderlaufen.
    half = hw * 0.26
    spread = hw * 0.40
    profiles = []
    for direction in (-1.0, 1.0):
        base_x = direction * spread * 0.62
        apex_x = direction * spread
        profiles.append([
            (base_x - half, top_y),
            (base_x + half, top_y),
            (apex_x + half * 0.72, top_y + height * 0.42),
            (apex_x + half * 0.40, top_y + height * 0.74),
            (apex_x, bottom_y),
            (apex_x - half * 0.40, top_y + height * 0.74),
            (apex_x - half * 0.72, top_y + height * 0.42),
        ])
    return profiles


def full_tooth_profile(tooth_class: str) -> tuple:
    """(kronen_polygon, [wurzel_polygone]) fuer einen kompletten Zahn im
    lokalen Einheitsquadrat: Kaufflaeche bei y=-0.5, Apex bei y=+0.5."""
    share = CROWN_HEIGHT_SHARE[tooth_class]
    neck_y = -0.5 + share

    # Kronenprofil in den oberen Abschnitt stauchen.
    crown = []
    for x, y in crown_profile(tooth_class):
        t = (y + 0.5)  # 0..1 innerhalb der Krone
        crown.append((x, -0.5 + t * share))

    roots = root_profiles(tooth_class, top_y=neck_y - 0.02, bottom_y=0.5)
    return crown, roots


def root_canal_lines(tooth_class: str, *, top_y: float, bottom_y: float) -> list:
    """Mittellinien der Wurzelkanaele (fuer die Wurzelbehandlungs-Darstellung),
    je Wurzel eine Linie vom Zahnhals bis kurz vor den Apex."""
    lines = []
    for profile in root_profiles(tooth_class, top_y=top_y, bottom_y=bottom_y):
        # Zahnhalsseitiger Startpunkt: Mitte der beiden obersten Punkte.
        top_points = sorted(profile, key=lambda p: p[1])[:2]
        start_x = sum(p[0] for p in top_points) / 2.0
        # Apex: der am weitesten apikal liegende Punkt des Profils (nicht ueber
        # einen festen Index, damit Aenderungen an der Wurzelform nicht
        # unbemerkt die Kanaellinien verbiegen).
        apex = max(profile, key=lambda p: p[1])
        inset = (bottom_y - top_y) * 0.06
        lines.append([(start_x, top_y), (apex[0], apex[1] - inset)])
    return lines
