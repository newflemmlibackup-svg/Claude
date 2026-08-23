"""Testhilfen: ein simulierter Bildschirm mit Fenstern und Knoepfen.

Damit laesst sich der komplette Weg (Aufnahme -> Speichern -> Wiederfinden
-> Klicken) ohne echten Mac und ohne echte Maus pruefen.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from klickpilot.config import DEFAULT_CONFIG  # noqa: E402
from klickpilot.inputs import InputBackend  # noqa: E402
from klickpilot.screen import Display, Frame, ScreenSource  # noqa: E402
from klickpilot.storage import Store  # noqa: E402

SCREEN_PIXELS = (1400, 2200)  # Hoehe, Breite
ROW_HEIGHT = 90
BUTTON_SIZE = (170, 54)


class SyntheticUI:
    """Zeichnet reproduzierbar ein Fenster mit einer Liste aus Zeilen.

    Jede Zeile hat links eine eigene Beschriftung (unterschiedliches Muster)
    und rechts einen Knopf. Wahlweise sehen alle Knoepfe exakt gleich aus -
    genau der Fall, in dem erst die Umgebung verraet, welcher gemeint ist.
    """

    def __init__(self, rows: int = 4, seed: int = 5):
        rng = np.random.default_rng(seed)
        self.rows = rows
        self.background = (rng.random((*SCREEN_PIXELS, 3)) * 26 + 196).astype(np.uint8)
        self.labels = [(rng.random((30, 120, 3)) * 200).astype(np.uint8) for _ in range(rows)]
        self.glyphs = [(rng.random((26, 90, 3)) * 190 + 20).astype(np.uint8) for _ in range(rows)]

    def render(self, origin: Tuple[int, int] = (300, 200), identical_buttons: bool = False,
               zoom: float = 1.0, brightness: int = 0) -> np.ndarray:
        image = self.background.copy()
        ox, oy = origin
        width, height = 700, 120 + self.rows * ROW_HEIGHT
        image[oy:oy + height, ox:ox + width] = 244
        image[oy:oy + 40, ox:ox + width] = 118
        image[oy + 8:oy + 30, ox + 16:ox + 136] = self.labels[0][:22, :120]
        for index in range(self.rows):
            top = oy + 70 + index * ROW_HEIGHT
            label = self.labels[index]
            image[top + 10:top + 10 + label.shape[0], ox + 150:ox + 150 + label.shape[1]] = label
            bx, by = ox + 320, top
            image[by:by + BUTTON_SIZE[1], bx:bx + BUTTON_SIZE[0]] = 208
            glyph = self.glyphs[0 if identical_buttons else index]
            image[by + 14:by + 14 + glyph.shape[0], bx + 40:bx + 40 + glyph.shape[1]] = glyph
        if brightness:
            image = np.clip(image.astype(np.int16) + brightness, 0, 255).astype(np.uint8)
        if zoom != 1.0:
            from klickpilot import imaging

            scaled = imaging.resize(image, (image.shape[1] * zoom, image.shape[0] * zoom))
            canvas = self.background.copy()
            cut_h = min(canvas.shape[0], scaled.shape[0])
            cut_w = min(canvas.shape[1], scaled.shape[1])
            canvas[:cut_h, :cut_w] = scaled[:cut_h, :cut_w]
            image = canvas
        return image

    def button_center(self, row: int, origin: Tuple[int, int] = (300, 200)) -> Tuple[float, float]:
        """Mittelpunkt des Knopfes in Bildschirm-Pixeln."""
        ox, oy = origin
        return (ox + 320 + BUTTON_SIZE[0] / 2, oy + 70 + row * ROW_HEIGHT + BUTTON_SIZE[1] / 2)


class FakeScreen(ScreenSource):
    def __init__(self, image: np.ndarray, scale: float = 2.0, display_id: int = 1):
        self.image = image
        self.scale = scale
        self.display_id = display_id
        self.captures = 0

    def displays(self) -> List[Display]:
        return [Display(self.display_id, (0.0, 0.0),
                        (self.image.shape[1] / self.scale, self.image.shape[0] / self.scale),
                        self.scale, True)]

    def capture(self, display: Optional[Display] = None) -> Frame:
        self.captures += 1
        return Frame(self.image, (0.0, 0.0), self.scale, self.display_id)

    def show(self, image: np.ndarray) -> None:
        self.image = image


class FakeInput(InputBackend):
    """Merkt sich alle ausgeloesten Aktionen, statt sie auszufuehren."""

    def __init__(self):
        self.actions: List[tuple] = []
        self.position = (0.0, 0.0)

    def mouse_position(self):
        return self.position

    def move(self, x, y):
        self.position = (x, y)
        self.actions.append(("move", x, y))

    def click(self, x, y, button="left", clicks=1, modifiers=()):
        self.position = (x, y)
        self.actions.append(("click", round(x, 1), round(y, 1), button, clicks, tuple(modifiers)))

    def drag(self, x1, y1, x2, y2, button="left"):
        self.actions.append(("drag", round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1), button))

    def scroll(self, x, y, dx, dy):
        self.actions.append(("scroll", round(x, 1), round(y, 1), dx, dy))

    def type_text(self, text, delay=0.0):
        self.actions.append(("text", text))

    def key(self, name, modifiers=()):
        self.actions.append(("key", name, tuple(modifiers)))


@pytest.fixture
def ui() -> SyntheticUI:
    return SyntheticUI()


@pytest.fixture
def store(tmp_path) -> Store:
    return Store(tmp_path / "buttons")


@pytest.fixture
def config() -> dict:
    values = dict(DEFAULT_CONFIG)
    values.update({"anchor_timeout": 0.4, "settle_after_click": 0.0, "countdown": 0})
    return values


@pytest.fixture
def inputs() -> FakeInput:
    return FakeInput()
