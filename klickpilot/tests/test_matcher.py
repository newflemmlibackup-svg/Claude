"""Prueft die Bildaehnlichkeitssuche - das Herzstueck des Programms."""
from __future__ import annotations

import numpy as np
import pytest

from klickpilot import imaging
from klickpilot.matcher import find_template, peaks, score_at, score_map


def naive_score_map(image, template):
    """Langsame, offensichtlich korrekte Referenz zum Vergleich."""
    height_img, width_img = image.shape
    height_tpl, width_tpl = template.shape
    result = np.zeros((height_img - height_tpl + 1, width_img - width_tpl + 1))
    tpl = template.astype(float)
    tpl = tpl - tpl.mean()
    tpl_norm = np.sqrt((tpl * tpl).sum())
    for y in range(result.shape[0]):
        for x in range(result.shape[1]):
            patch = image[y:y + height_tpl, x:x + width_tpl].astype(float)
            patch = patch - patch.mean()
            denominator = np.sqrt((patch * patch).sum()) * tpl_norm
            result[y, x] = (patch * tpl).sum() / denominator if denominator > 1e-9 else 0.0
    return result


def test_score_map_matches_reference():
    rng = np.random.default_rng(2)
    image = (rng.random((50, 70)) * 255).astype(np.uint8)
    template = image[12:28, 30:52].copy()
    assert np.abs(score_map(image, template) - naive_score_map(image, template)).max() < 1e-9


def test_score_map_finds_exact_position():
    rng = np.random.default_rng(3)
    image = (rng.random((60, 90)) * 255).astype(np.uint8)
    template = image[20:36, 40:60].copy()
    values = score_map(image, template)
    y, x = np.unravel_index(int(values.argmax()), values.shape)
    assert (x, y) == (40, 20)
    assert values.max() == pytest.approx(1.0)


def test_score_map_survives_brightness_and_contrast():
    rng = np.random.default_rng(4)
    image = (rng.random((60, 90)) * 255).astype(np.uint8)
    template = image[10:30, 20:50].copy()
    changed = np.clip(image.astype(float) * 0.75 + 45, 0, 255).astype(np.uint8)
    assert score_map(changed, template).max() > 0.99


def test_score_map_rejects_too_large_template():
    assert score_map(np.zeros((10, 10), np.uint8), np.zeros((20, 20), np.uint8)) is None


def test_score_map_handles_uniform_template():
    values = score_map(np.zeros((10, 10), np.uint8), np.full((3, 3), 7, np.uint8))
    assert values is not None and np.all(values == 0)


def test_score_at_partial_overlap():
    rng = np.random.default_rng(5)
    image = (rng.random((40, 40)) * 255).astype(np.uint8)
    template = image[0:20, 0:20].copy()
    assert score_at(image, template, 0, 0) == pytest.approx(1.0)
    # Weniger als die Haelfte im Bild -> unbrauchbar.
    assert score_at(image, template, -18, 0) == 0.0


def test_peaks_are_spatially_separated():
    values = np.zeros((40, 40))
    values[10, 10] = 0.9
    values[11, 11] = 0.88   # gleicher Berg
    values[30, 30] = 0.8
    found = peaks(values, 2, 8, 8)
    assert [(round(s, 2), x, y) for s, x, y in found] == [(0.9, 10, 10), (0.8, 30, 30)]


def test_find_template_locates_moved_window(ui):
    template_region = ui.render((300, 200))[240:340, 600:820]
    moved = ui.render((1100, 700))
    matches = find_template(imaging.to_gray(moved), imaging.to_gray(template_region))
    assert matches, "kein Treffer gefunden"
    best = matches[0]
    assert best.score > 0.9
    assert abs(best.x - (600 + 800)) <= 2 and abs(best.y - (240 + 500)) <= 2


def test_find_template_handles_zoomed_window(ui):
    template_region = ui.render((300, 200))[240:340, 600:820]
    zoomed = ui.render((300, 200), zoom=1.08)
    matches = find_template(imaging.to_gray(zoomed), imaging.to_gray(template_region))
    assert matches and matches[0].score > 0.8
    assert matches[0].scale == pytest.approx(1.08, abs=0.05)


def test_find_template_reports_low_score_for_missing_element(ui):
    rng = np.random.default_rng(9)
    template = (rng.random((60, 120)) * 255).astype(np.uint8)
    matches = find_template(imaging.to_gray(ui.render()), template)
    assert not matches or matches[0].score < 0.5
