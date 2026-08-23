"""Anker anlegen (Aufnahme) und wiederfinden (Wiedergabe).

Beim Aufnehmen wird um jeden Klickpunkt ein enger Ausschnitt (die
"Schablone") und ein grosser Umgebungsausschnitt gesichert. Beim Abspielen
wird die Schablone auf dem aktuellen Bildschirm gesucht - dadurch ist die
gespeicherte Bildschirmkoordinate nur noch ein Hinweis, kein Muss.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import imaging
from .matcher import DEFAULT_SCALES, Match, find_template, score_at
from .models import Anchor
from .screen import Frame, ScreenSource
from .storage import Store


@dataclass
class Located:
    """Fundstelle eines Ankers auf dem aktuellen Bildschirm."""

    point: Tuple[float, float]
    score: float
    display_id: int
    match: Match
    frame: Frame


class AnchorFactory:
    """Erzeugt aus Bildschirmfoto + Klickpunkt einen gespeicherten Anker."""

    def __init__(self, store: Store, slug: str, config: dict):
        self.store = store
        self.slug = slug
        self.config = config
        self._index = store.next_asset_index(slug)

    def make(self, frame: Frame, point: Tuple[float, float]) -> Anchor:
        pixel_x, pixel_y = frame.point_to_pixel(point)
        template_pt = self.config.get("template_size", [160, 110])
        context_pt = self.config.get("context_size", [440, 300])
        scale = frame.scale or 1.0

        patch, ox, oy = imaging.crop_around(
            frame.image, pixel_x, pixel_y, template_pt[0] * scale, template_pt[1] * scale
        )
        context, cx, cy = imaging.crop_around(
            frame.image, pixel_x, pixel_y, context_pt[0] * scale, context_pt[1] * scale
        )

        name = f"a{self._index:04d}.png"
        context_name = f"a{self._index:04d}_ctx.png"
        self._index += 1
        self.store.store_asset(self.slug, patch, name)
        self.store.store_asset(self.slug, context, context_name)

        return Anchor(
            template=name,
            size=(patch.shape[1], patch.shape[0]),
            hotspot=(pixel_x - ox, pixel_y - oy),
            context=context_name,
            context_size=(context.shape[1], context.shape[0]),
            context_hotspot=(pixel_x - cx, pixel_y - cy),
            point=(float(point[0]), float(point[1])),
            display_id=frame.display_id,
            scale=scale,
        )


class TemplateCache:
    """Haelt geladene Schablonen als Graubilder vor."""

    def __init__(self, store: Store):
        self.store = store
        self._cache: Dict[Tuple[str, str], Optional[np.ndarray]] = {}

    def gray(self, slug: str, name: str) -> Optional[np.ndarray]:
        if not name:
            return None
        key = (slug, name)
        if key not in self._cache:
            image = self.store.load_asset(slug, name)
            self._cache[key] = imaging.to_gray(image) if image is not None else None
        return self._cache[key]

    def clear(self) -> None:
        self._cache.clear()


class AnchorNotFound(RuntimeError):
    """Das gesuchte Bedienelement war auf dem Bildschirm nicht auffindbar."""

    def __init__(self, message: str, best: float = 0.0):
        super().__init__(message)
        self.best = best


class AnchorLocator:
    """Sucht Anker auf dem Bildschirm - das Herz der Wiedergabe."""

    def __init__(self, screen: ScreenSource, store: Store, config: dict,
                 cache: Optional[TemplateCache] = None):
        self.screen = screen
        self.store = store
        self.config = config
        self.cache = cache or TemplateCache(store)
        self.last_score = 0.0

    # -- Einzelversuch ---------------------------------------------------
    def locate_once(self, slug: str, anchor: Anchor,
                    scales: Sequence[float] = DEFAULT_SCALES) -> Optional[Located]:
        template = self.cache.gray(slug, anchor.template)
        if template is None:
            return None
        context = self.cache.gray(slug, anchor.context)
        best: Optional[Located] = None

        for frame in self._frames_to_search(anchor):
            factor = (frame.scale or 1.0) / (anchor.scale or 1.0)
            search_template = template
            if abs(factor - 1.0) > 0.02:
                search_template = imaging.resize(
                    template, (template.shape[1] * factor, template.shape[0] * factor)
                )
            if min(search_template.shape) < 4:
                continue
            candidates = find_template(frame.gray, search_template, scales=scales)
            for match in candidates[:4]:
                total = self._combined_score(frame, anchor, match, template, context)
                located = self._to_located(frame, anchor, match, template, total)
                if best is None or located.score > best.score:
                    best = located
            if best is not None and best.score >= self._threshold(anchor):
                break

        self.last_score = best.score if best else 0.0
        return best

    def _threshold(self, anchor: Anchor) -> float:
        if anchor.threshold is not None:
            return float(anchor.threshold)
        return float(self.config.get("match_threshold", 0.78))

    def _frames_to_search(self, anchor: Anchor) -> List[Frame]:
        """Erst den Bildschirm der Aufnahme, dann alle uebrigen."""
        displays = self.screen.displays()
        ordered = [d for d in displays if d.display_id == anchor.display_id]
        ordered += [d for d in displays if d.display_id != anchor.display_id]
        frames: List[Frame] = []
        for display in ordered or displays:
            try:
                frames.append(self.screen.capture(display))
            except Exception:
                continue
        return frames

    def _combined_score(self, frame: Frame, anchor: Anchor, match: Match,
                        template: np.ndarray, context: Optional[np.ndarray]) -> float:
        """Bezieht den Umgebungsausschnitt ein, um Verwechslungen zu vermeiden.

        Sieht ein Element mehrfach gleich aus (z. B. zehn identische Knoepfe
        in einer Liste), entscheidet die Umgebung, welches gemeint war.
        """
        weight = float(self.config.get("context_weight", 0.35))
        if context is None or weight <= 0 or not anchor.size[0]:
            return match.score
        factor = match.width / float(anchor.size[0])
        scaled_context = imaging.resize(
            context, (context.shape[1] * factor, context.shape[0] * factor)
        )
        if min(scaled_context.shape) < 4:
            return match.score
        click_x = match.x + anchor.hotspot[0] * factor
        click_y = match.y + anchor.hotspot[1] * factor
        origin_x = click_x - anchor.context_hotspot[0] * factor
        origin_y = click_y - anchor.context_hotspot[1] * factor
        context_score = score_at(frame.gray, scaled_context, origin_x, origin_y)
        match.context_score = context_score
        return (1.0 - weight) * match.score + weight * context_score

    def _to_located(self, frame: Frame, anchor: Anchor, match: Match,
                    template: np.ndarray, score: float) -> Located:
        pixel = match.point_at(anchor.hotspot, (anchor.size[0] or template.shape[1],
                                                anchor.size[1] or template.shape[0]))
        return Located(
            point=frame.pixel_to_point(pixel),
            score=score,
            display_id=frame.display_id,
            match=match,
            frame=frame,
        )

    # -- Mit Wiederholung ------------------------------------------------
    def locate(self, slug: str, anchor: Anchor, timeout: Optional[float] = None,
               should_stop=None, poll: float = 0.35) -> Located:
        """Wartet bis zu ``timeout`` Sekunden auf das Bedienelement."""
        limit = float(timeout if timeout is not None else self.config.get("anchor_timeout", 8.0))
        threshold = self._threshold(anchor)
        deadline = time.time() + max(0.0, limit)
        best_score = 0.0
        while True:
            if should_stop is not None and should_stop():
                raise AnchorNotFound("Abgebrochen.", best_score)
            located = self.locate_once(slug, anchor)
            if located is not None:
                best_score = max(best_score, located.score)
                if located.score >= threshold:
                    return located
            if time.time() >= deadline:
                break
            time.sleep(poll)
        raise AnchorNotFound(
            f"Bedienelement nicht gefunden (beste Aehnlichkeit {best_score:.0%}, "
            f"noetig waeren {threshold:.0%}).",
            best_score,
        )

    def wait_until_gone(self, slug: str, anchor: Anchor, timeout: Optional[float] = None,
                        should_stop=None, poll: float = 0.35) -> bool:
        limit = float(timeout if timeout is not None else self.config.get("anchor_timeout", 8.0))
        threshold = self._threshold(anchor)
        deadline = time.time() + max(0.0, limit)
        while time.time() < deadline:
            if should_stop is not None and should_stop():
                return False
            located = self.locate_once(slug, anchor)
            if located is None or located.score < threshold:
                return True
            time.sleep(poll)
        return False
