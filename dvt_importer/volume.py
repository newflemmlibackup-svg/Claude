"""Schichtplan eines DVT-Volumens: Reihenfolge, Geometrie und Lückenerkennung.

Aus den Header-Angaben aller gefundenen Schichten wird eine lückenlose,
gleichmäßig verteilte Schichtfolge berechnet. Stellen, an denen Schichten
fehlen, erscheinen im Plan als `None` und werden später schwarz aufgefüllt.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DEFAULT_IOP = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
# Sicherheitsgrenze: Sind angeblich mehr Schichten verloren als vorhanden, sind die
# Abstände unregelmäßig und keine echten Lücken - dann wird nichts aufgefüllt.
MAX_FILL_RATIO = 1.0


@dataclass
class SliceRef:
    """Verweis auf eine Schicht: Datei, ggf. Frame-Index bei Multiframe-Dateien."""

    path: Path
    frame: Optional[int] = None
    instance_number: Optional[int] = None
    position: Optional[tuple] = None


@dataclass
class VolumePlan:
    slots: list                      # list[SliceRef | None]; None = fehlende Schicht
    iop: tuple                       # ImageOrientationPatient (6 Werte)
    origin: tuple                    # Position der ersten Schicht
    step: tuple                      # Vektor von Schicht zu Schicht (mm)
    slice_spacing: float             # Betrag von step (mm)
    pixel_spacing: tuple             # (Zeile, Spalte) in mm
    spacing_known: bool = True
    notes: list = field(default_factory=list)

    @property
    def num_missing(self) -> int:
        return sum(1 for s in self.slots if s is None)

    @property
    def num_found(self) -> int:
        return len(self.slots) - self.num_missing

    def position_of(self, index: int) -> tuple:
        return tuple(self.origin[k] + index * self.step[k] for k in range(3))


def _normal(iop) -> tuple:
    r, c = iop[:3], iop[3:]
    n = (r[1] * c[2] - r[2] * c[1], r[2] * c[0] - r[0] * c[2], r[0] * c[1] - r[1] * c[0])
    length = sum(v * v for v in n) ** 0.5
    if length < 1e-6:
        return (0.0, 0.0, 1.0)
    return tuple(v / length for v in n)


def _natural_key(path: Path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path.name)]


def _fill_gaps(ordered, values, unit):
    """Fügt None-Platzhalter ein, wo zwischen Nachbarn mehr als eine Einheit liegt."""
    slots, missing = [ordered[0]], 0
    for prev, cur, ref in zip(values, values[1:], ordered[1:]):
        k = max(1, int(round((cur - prev) / unit)))
        slots.extend([None] * (k - 1))
        missing += k - 1
        slots.append(ref)
    return slots, missing


def build_plan(slices, iop=None, pixel_spacing=None, slice_spacing_hint=None,
               origin_hint=None) -> VolumePlan:
    notes = []
    if iop is None:
        iop = DEFAULT_IOP
        notes.append("Bildorientierung fehlte, axiale Standardlage angenommen")
    normal = _normal(iop)

    with_pos = [s for s in slices if s.position is not None]
    slots = None
    spacing = None
    origin = None
    direction = 1.0

    # --- 1. Wahl: Sortierung nach räumlicher Position ---------------------
    if len(with_pos) >= 2 and len(with_pos) >= 0.9 * len(slices):
        proj = lambda s: sum(s.position[k] * normal[k] for k in range(3))  # noqa: E731
        ordered = sorted(with_pos, key=proj)
        values = [proj(s) for s in ordered]
        diffs = [b - a for a, b in zip(values, values[1:]) if b - a > 1e-4]
        if diffs:
            unit = statistics.median(diffs)
            # Doppelte Schichten (gleiche Position) verwerfen.
            keep, keep_vals = [ordered[0]], [values[0]]
            for ref, val in zip(ordered[1:], values[1:]):
                if val - keep_vals[-1] >= 0.5 * unit:
                    keep.append(ref)
                    keep_vals.append(val)
            dropped = len(ordered) - len(keep)
            if dropped:
                notes.append(f"{dropped} doppelte Schicht(en) verworfen")
            if len(with_pos) < len(slices):
                notes.append(f"{len(slices) - len(with_pos)} Schicht(en) ohne Positionsangabe verworfen")

            slots, missing = _fill_gaps(keep, keep_vals, unit)
            if missing > MAX_FILL_RATIO * len(keep):
                notes.append("Schichtabstände unregelmäßig – Lücken können nicht sicher erkannt werden")
                slots = list(keep)
            spacing = (keep_vals[-1] - keep_vals[0]) / (len(slots) - 1) if len(slots) > 1 else unit

            # Reihenfolge der ursprünglichen Bildnummern beibehalten.
            nums = [(i, s.instance_number) for i, s in enumerate(slots)
                    if s is not None and s.instance_number is not None]
            if len(nums) >= 2 and nums[-1][1] < nums[0][1]:
                slots.reverse()
                direction = -1.0
            origin = slots[0].position

    # --- 2. Wahl: Sortierung nach Bildnummer ------------------------------
    if slots is None:
        nums = [s.instance_number for s in slices]
        if all(n is not None for n in nums) and len(set(nums)) == len(nums):
            ordered = sorted(slices, key=lambda s: s.instance_number)
            values = [s.instance_number for s in ordered]
            slots, missing = _fill_gaps(ordered, values, 1)
            if missing > MAX_FILL_RATIO * len(ordered):
                slots = list(ordered)
        else:
            slots = sorted(slices, key=lambda s: (_natural_key(s.path), s.frame or 0))
            notes.append("Keine Positions-/Nummernangaben – Sortierung nach Dateiname, "
                         "Lückenerkennung nicht möglich")

    spacing_known = True
    if pixel_spacing is None:
        spacing_known = False
    if spacing is None or spacing <= 0:
        if slice_spacing_hint and slice_spacing_hint > 0:
            spacing = float(slice_spacing_hint)
        elif pixel_spacing is not None:
            spacing = float(pixel_spacing[0])   # DVT-Voxel sind üblicherweise würfelförmig
            notes.append("Schichtabstand fehlte, Voxel als würfelförmig angenommen")
        else:
            spacing = 0.3
            spacing_known = False
    if pixel_spacing is None:
        pixel_spacing = (spacing, spacing)
    if not spacing_known:
        notes.append("ACHTUNG: Voxelgröße unbekannt – Längenmessungen sind nicht verlässlich")

    if origin is None:
        origin = tuple(origin_hint) if origin_hint else (0.0, 0.0, 0.0)
    step = tuple(direction * spacing * n for n in normal)

    plan = VolumePlan(
        slots=slots, iop=tuple(float(v) for v in iop), origin=tuple(float(v) for v in origin),
        step=step, slice_spacing=float(spacing),
        pixel_spacing=(float(pixel_spacing[0]), float(pixel_spacing[1])),
        spacing_known=spacing_known, notes=notes,
    )
    if plan.num_missing:
        notes.insert(0, f"{plan.num_missing} fehlende Schicht(en) werden schwarz ergänzt")
    return plan
