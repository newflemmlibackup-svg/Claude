"""Wiedererkennung von Bedienelementen per Bildaehnlichkeit.

Kernstueck des Programms: Statt gespeicherte Mauskoordinaten stumpf erneut
anzufahren, wird der bei der Aufnahme gemerkte Bildausschnitt ("Schablone")
auf dem aktuellen Bildschirm gesucht. Verschiebt sich ein Dialog, wandert
das Fenster oder aendert sich die Fenstergroesse, wird der Knopf trotzdem
gefunden.

Verfahren: normierte Kreuzkorrelation (ZNCC). Sie ist unempfindlich gegen
Helligkeits- und Kontrastaenderungen und liefert einen Wert zwischen -1 und
1 (1 = identisch). Gerechnet wird zweistufig - erst grob auf einem
verkleinerten Bildschirmfoto, dann fein in voller Aufloesung rund um die
besten Kandidaten. Das ist um Groessenordnungen schneller als eine volle
Suche und zugleich robuster gegen Fehltreffer.

Zusaetzlich kann zu jeder Schablone ein groesserer Umgebungsausschnitt
hinterlegt sein (siehe :mod:`klickpilot.anchors`). Er entscheidet, wenn
mehrere gleich aussehende Elemente gefunden werden - etwa zehn identische
"Loeschen"-Knoepfe in einer Liste.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import imaging

# Groessenabweichungen, die zusaetzlich geprueft werden (z. B. veraenderte
# Zoomstufe der Zielanwendung oder anderes Display-Scaling).
DEFAULT_SCALES: Tuple[float, ...] = (1.0, 0.92, 1.08, 0.84, 1.18)
COARSE_WIDTH = 720
MIN_COARSE_TEMPLATE = 14
# So viele Groessenvarianten werden je Kandidat fein nachgerechnet.
REFINE_SCALES = 2


@dataclass
class Match:
    """Fundstelle einer Schablone im Bildschirmfoto (Pixel des Fotos)."""

    score: float
    x: int
    y: int
    width: int
    height: int
    scale: float = 1.0
    context_score: Optional[float] = None

    @property
    def center(self) -> Tuple[float, float]:
        return (self.x + self.width / 2.0, self.y + self.height / 2.0)

    def point_at(self, hotspot: Tuple[float, float], template_size: Tuple[int, int]) -> Tuple[float, float]:
        """Rechnet einen Punkt der Original-Schablone auf die Fundstelle um."""
        tw, th = template_size
        fx = self.width / float(tw) if tw else 1.0
        fy = self.height / float(th) if th else 1.0
        return (self.x + hotspot[0] * fx, self.y + hotspot[1] * fy)


def _next_fast_len(n: int) -> int:
    """Naechste Laenge, die sich in kleine Primfaktoren (2,3,5) zerlegt."""
    n = int(n)
    if n <= 8:
        return max(1, n)
    best = n
    while True:
        rest = best
        for factor in (2, 3, 5):
            while rest % factor == 0:
                rest //= factor
        if rest == 1:
            return best
        best += 1


class Correlator:
    """Vorberechnung fuer ein Bild, in dem mehrere Schablonen gesucht werden.

    Spektrum und Integralbilder haengen nur vom Bild ab, nicht von der
    Schablone. Werden sie einmal berechnet und fuer alle Groessenvarianten
    wiederverwendet, halbiert das die Rechenzeit.
    """

    def __init__(self, image: np.ndarray, max_template_shape: Tuple[int, int]):
        self.image = image.astype(np.float64, copy=False)
        height, width = self.image.shape
        self.max_shape = (int(max_template_shape[0]), int(max_template_shape[1]))
        self.fft_shape = (
            _next_fast_len(height + self.max_shape[0] - 1),
            _next_fast_len(width + self.max_shape[1] - 1),
        )
        self._spectrum = np.fft.rfft2(self.image, self.fft_shape)
        self._integral = _integral_image(self.image)
        self._integral_squared = _integral_image(self.image * self.image)

    def fits(self, template_shape: Tuple[int, int]) -> bool:
        return (
            template_shape[0] <= self.max_shape[0]
            and template_shape[1] <= self.max_shape[1]
            and template_shape[0] <= self.image.shape[0]
            and template_shape[1] <= self.image.shape[1]
        )

    def score_map(self, template: np.ndarray) -> Optional[np.ndarray]:
        """ZNCC-Wertekarte fuer alle moeglichen Positionen der Schablone."""
        if not self.fits(template.shape):
            return None
        height_img, width_img = self.image.shape
        height_tpl, width_tpl = template.shape
        area = float(height_tpl * width_tpl)

        tpl = template.astype(np.float64, copy=False)
        tpl_zero = tpl - tpl.mean()
        tpl_norm = float(np.sqrt((tpl_zero * tpl_zero).sum()))
        rows = height_img - height_tpl + 1
        columns = width_img - width_tpl + 1
        if tpl_norm < 1e-9:
            # Vollkommen einfarbige Schablone - jede Aussage waere Zufall.
            return np.zeros((rows, columns))

        spectrum = self._spectrum * np.conj(np.fft.rfft2(tpl_zero, self.fft_shape))
        numerator = np.fft.irfft2(spectrum, self.fft_shape)[:rows, :columns]

        sums = _window_sums(self._integral, height_tpl, width_tpl)
        squares = _window_sums(self._integral_squared, height_tpl, width_tpl)
        variance = squares - (sums * sums) / area
        denominator = np.sqrt(np.maximum(variance, 0.0)) * tpl_norm

        result = np.zeros_like(numerator)
        usable = denominator > 1e-9
        result[usable] = numerator[usable] / denominator[usable]
        return np.clip(result, -1.0, 1.0)


def _integral_image(image: np.ndarray) -> np.ndarray:
    integral = np.zeros((image.shape[0] + 1, image.shape[1] + 1), dtype=np.float64)
    integral[1:, 1:] = image.cumsum(axis=0).cumsum(axis=1)
    return integral


def _window_sums(integral: np.ndarray, height: int, width: int) -> np.ndarray:
    return (
        integral[height:, width:]
        - integral[:-height, width:]
        - integral[height:, :-width]
        + integral[:-height, :-width]
    )


def score_map(image: np.ndarray, template: np.ndarray) -> Optional[np.ndarray]:
    """ZNCC-Wertekarte (Form ``(H - h + 1, W - w + 1)``) oder ``None``."""
    if template.shape[0] > image.shape[0] or template.shape[1] > image.shape[1]:
        return None
    return Correlator(image, template.shape).score_map(template)


def score_at(image: np.ndarray, template: np.ndarray, x: float, y: float) -> float:
    """ZNCC an genau einer Position, auch teilweise ausserhalb des Bildes.

    Ragt die Schablone ueber den Bildrand hinaus, wird nur die Schnittmenge
    bewertet; bei weniger als der Haelfte Ueberlappung gilt der Treffer als
    wertlos (0.0).
    """
    height_img, width_img = image.shape
    height_tpl, width_tpl = template.shape
    x0, y0 = int(round(x)), int(round(y))
    ix0, iy0 = max(0, x0), max(0, y0)
    ix1, iy1 = min(width_img, x0 + width_tpl), min(height_img, y0 + height_tpl)
    if ix1 - ix0 < 2 or iy1 - iy0 < 2:
        return 0.0
    if (ix1 - ix0) * (iy1 - iy0) < 0.5 * width_tpl * height_tpl:
        return 0.0
    patch = image[iy0:iy1, ix0:ix1].astype(np.float64, copy=False)
    part = template[iy0 - y0:iy1 - y0, ix0 - x0:ix1 - x0].astype(np.float64, copy=False)
    patch = patch - patch.mean()
    part = part - part.mean()
    denominator = float(np.sqrt((patch * patch).sum()) * np.sqrt((part * part).sum()))
    if denominator < 1e-9:
        return 0.0
    return float(np.clip((patch * part).sum() / denominator, -1.0, 1.0))


def peaks(values: np.ndarray, count: int, width: int, height: int) -> List[Tuple[float, int, int]]:
    """Die ``count`` besten, raeumlich getrennten Maxima einer Wertekarte."""
    work = values.copy()
    found: List[Tuple[float, int, int]] = []
    # Der Sperrbereich um ein gefundenes Maximum ist bewusst klein: In Listen
    # liegen gleichartige Eintraege dicht beieinander und muessen einzeln als
    # Kandidat erhalten bleiben.
    keep_out_x = max(2, width // 4)
    keep_out_y = max(2, height // 4)
    for _ in range(count):
        index = int(np.argmax(work))
        y, x = np.unravel_index(index, work.shape)
        score = float(work[y, x])
        if score <= -1.0:
            break
        found.append((score, int(x), int(y)))
        work[
            max(0, y - keep_out_y):y + keep_out_y + 1,
            max(0, x - keep_out_x):x + keep_out_x + 1,
        ] = -2.0
    return found


def find_template(
    image: np.ndarray,
    template: np.ndarray,
    *,
    scales: Sequence[float] = DEFAULT_SCALES,
    candidates: int = 4,
    coarse_width: int = COARSE_WIDTH,
) -> List[Match]:
    """Sucht die Schablone im Bild und liefert die besten Fundstellen.

    Beide Bilder muessen Graubilder sein. Die Liste ist absteigend nach
    Aehnlichkeit sortiert.
    """
    if image.ndim != 2:
        image = imaging.to_gray(image)
    if template.ndim != 2:
        template = imaging.to_gray(template)
    height_tpl, width_tpl = template.shape
    if height_tpl < 3 or width_tpl < 3:
        return []
    if image.shape[0] < 3 or image.shape[1] < 3:
        return []

    factor = _coarse_factor(image.shape, template.shape, coarse_width)
    if factor <= 1.0:
        return _direct_search(image, template, scales, candidates)

    # 1. Grobsuche auf dem verkleinerten Bildschirmfoto.
    small_image = imaging.scaled(image, 1.0 / factor)
    largest = max(scales)
    correlator = Correlator(small_image, (
        min(small_image.shape[0], int(height_tpl * largest / factor) + 2),
        min(small_image.shape[1], int(width_tpl * largest / factor) + 2),
    ))
    rough: List[Tuple[float, float, float, float]] = []  # Wert, Mitte x, Mitte y, Groesse
    for scale in scales:
        small_template = imaging.resize(
            template, (width_tpl * scale / factor, height_tpl * scale / factor)
        )
        if min(small_template.shape) < 4:
            continue
        values = correlator.score_map(small_template)
        if values is None:
            continue
        for score, x, y in peaks(values, candidates, small_template.shape[1], small_template.shape[0]):
            rough.append((
                score,
                (x + small_template.shape[1] / 2.0) * factor,
                (y + small_template.shape[0] / 2.0) * factor,
                scale,
            ))
    rough.sort(key=lambda item: item[0], reverse=True)

    # 2. Feinsuche in voller Aufloesung rund um jeden Kandidaten. Bezugspunkt
    #    ist der Mittelpunkt, damit verschiedene Groessen vergleichbar sind.
    centers = _pick_centers(rough, width_tpl, height_tpl, candidates)
    margin = int(factor * 2 + 8)
    results: List[Match] = []
    for center, wanted in centers:
        best: Optional[Match] = None
        for scale in wanted:
            refined = _refine(image, template, scale, center[0], center[1], margin)
            if refined is not None and (best is None or refined.score > best.score):
                best = refined
        if best is not None:
            results.append(best)
    results.sort(key=lambda match: match.score, reverse=True)
    return results


def _pick_centers(rough, width_tpl: int, height_tpl: int, candidates: int):
    """Waehlt getrennte Kandidatenpunkte samt der dort passenden Groessen."""
    keep_out_x = max(4.0, width_tpl / 4.0)
    keep_out_y = max(4.0, height_tpl / 4.0)
    centers: List[Tuple[Tuple[float, float], List[float]]] = []
    scales_by_center: List[Dict[float, float]] = []
    for score, cx, cy, scale in rough:
        index = None
        for position, (center, _scales) in enumerate(centers):
            if abs(cx - center[0]) < keep_out_x and abs(cy - center[1]) < keep_out_y:
                index = position
                break
        if index is None:
            if len(centers) >= candidates:
                continue
            centers.append(((cx, cy), []))
            scales_by_center.append({scale: score})
        else:
            scales_by_center[index].setdefault(scale, score)
    result = []
    for (center, _), by_scale in zip(centers, scales_by_center):
        ordered = sorted(by_scale.items(), key=lambda item: item[1], reverse=True)
        wanted = [scale for scale, _score in ordered[:REFINE_SCALES]]
        if 1.0 in by_scale and 1.0 not in wanted:
            wanted.append(1.0)
        result.append((center, wanted))
    return result


def _coarse_factor(image_shape, template_shape, coarse_width: int) -> float:
    by_image = image_shape[1] / float(coarse_width)
    by_template = min(template_shape) / float(MIN_COARSE_TEMPLATE)
    return max(1.0, min(by_image, max(1.0, by_template)))


def _direct_search(image, template, scales, candidates) -> List[Match]:
    """Kleine Bilder: ohne Vorstufe direkt in voller Aufloesung suchen."""
    results: List[Match] = []
    height_tpl, width_tpl = template.shape
    largest = max(scales)
    correlator = Correlator(image, (
        min(image.shape[0], int(height_tpl * largest) + 2),
        min(image.shape[1], int(width_tpl * largest) + 2),
    ))
    for scale in scales:
        scaled_template = imaging.resize(template, (width_tpl * scale, height_tpl * scale))
        values = correlator.score_map(scaled_template)
        if values is None:
            continue
        for score, x, y in peaks(values, candidates, scaled_template.shape[1], scaled_template.shape[0]):
            results.append(
                Match(score, x, y, scaled_template.shape[1], scaled_template.shape[0], scale)
            )
    results.sort(key=lambda match: match.score, reverse=True)
    return _deduplicate(results, candidates)


def _deduplicate(matches: List[Match], count: int) -> List[Match]:
    kept: List[Match] = []
    for match in matches:
        if any(
            abs(match.center[0] - other.center[0]) < max(4, other.width / 4)
            and abs(match.center[1] - other.center[1]) < max(4, other.height / 4)
            for other in kept
        ):
            continue
        kept.append(match)
        if len(kept) >= count:
            break
    return kept


def _refine(image, template, scale, center_x, center_y, margin) -> Optional[Match]:
    """Feinsuche in voller Aufloesung um einen Kandidaten-Mittelpunkt."""
    height_tpl, width_tpl = template.shape
    width = max(3, int(round(width_tpl * scale)))
    height = max(3, int(round(height_tpl * scale)))
    scaled_template = imaging.resize(template, (width, height))
    left = center_x - width / 2.0
    top = center_y - height / 2.0
    region, ox, oy = imaging.crop(
        image, left - margin, top - margin, width + 2 * margin, height + 2 * margin
    )
    values = score_map(region, scaled_template)
    if values is None:
        score = score_at(image, scaled_template, left, top)
        return Match(score, int(round(left)), int(round(top)), width, height, scale)
    index = int(np.argmax(values))
    y, x = np.unravel_index(index, values.shape)
    return Match(float(values[y, x]), int(ox + x), int(oy + y), width, height, scale)
