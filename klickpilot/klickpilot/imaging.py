"""Kleine Bildhilfsfunktionen auf Basis von numpy/Pillow.

Bildschirminhalte werden als numpy-Arrays gehalten:
  * Farbbild : uint8, Form (H, W, 3), RGB
  * Graubild : uint8, Form (H, W)
"""
from __future__ import annotations

from pathlib import Path
from typing import Tuple

import numpy as np
from PIL import Image


def to_gray(image: np.ndarray) -> np.ndarray:
    """Wandelt ein RGB-Bild in ein 8-Bit-Graubild (Luma-Gewichtung)."""
    if image.ndim == 2:
        return image if image.dtype == np.uint8 else image.astype(np.uint8)
    if image.shape[2] == 4:
        image = image[:, :, :3]
    weights = np.array([0.299, 0.587, 0.114], dtype=np.float32)
    gray = image[:, :, :3].astype(np.float32) @ weights
    return np.clip(gray + 0.5, 0, 255).astype(np.uint8)


def resize(image: np.ndarray, size: Tuple[int, int]) -> np.ndarray:
    """Skaliert auf (Breite, Hoehe). Verkleinern per Flaechenmittel."""
    width = max(1, int(round(size[0])))
    height = max(1, int(round(size[1])))
    if image.shape[1] == width and image.shape[0] == height:
        return image
    shrinking = width < image.shape[1] or height < image.shape[0]
    resample = Image.BOX if shrinking else Image.BILINEAR
    return np.asarray(Image.fromarray(image).resize((width, height), resample))


def scaled(image: np.ndarray, factor: float) -> np.ndarray:
    return resize(image, (image.shape[1] * factor, image.shape[0] * factor))


def crop(image: np.ndarray, x: int, y: int, width: int, height: int) -> Tuple[np.ndarray, int, int]:
    """Schneidet aus, ohne den Bildrand zu ueberschreiten.

    Rueckgabe: (Ausschnitt, tatsaechliches x, tatsaechliches y).
    """
    height_img, width_img = image.shape[:2]
    width = max(1, min(int(width), width_img))
    height = max(1, min(int(height), height_img))
    x = int(max(0, min(int(x), width_img - width)))
    y = int(max(0, min(int(y), height_img - height)))
    return image[y:y + height, x:x + width], x, y


def crop_around(image: np.ndarray, cx: float, cy: float, width: int, height: int):
    """Ausschnitt moeglichst mittig um (cx, cy) - Randfaelle werden verschoben."""
    return crop(image, round(cx - width / 2.0), round(cy - height / 2.0), width, height)


def load_image(path: str | Path) -> np.ndarray:
    with Image.open(path) as handle:
        return np.asarray(handle.convert("L" if handle.mode in ("L", "1") else "RGB"))


def save_image(path: str | Path, image: np.ndarray) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image).save(path, format="PNG", optimize=True)


def difference(a: np.ndarray, b: np.ndarray) -> float:
    """Mittlere Helligkeitsabweichung zweier Bilder (0..1), zur Ruhe-Erkennung."""
    if a.shape != b.shape:
        b = resize(b, (a.shape[1], a.shape[0]))
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean() / 255.0)
