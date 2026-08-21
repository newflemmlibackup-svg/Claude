"""Rendert einen Behandlungsplan (OPG + Befund-Symbole) als PIL-Bild - fuer
den PDF-Export sowie einen optionalen PNG-Export. Nutzt dieselbe Geometrie
(shapes.build_draw_ops) wie die Tkinter-Canvas-Ansicht, damit Bildschirm und
Export identisch aussehen.

Flaechenfuellungen werden halbtransparent gezeichnet, damit die darunter
liegende Roentgenstruktur sichtbar bleibt.
"""
from __future__ import annotations

import math
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from . import shapes
from .models import TreatmentPlan

FILL_ALPHA = 150
CALIBRATION_COLOR = (0, 150, 140, 255)


def _hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple:
    hex_color = hex_color.lstrip("#")
    r, g, b = tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return (r, g, b, alpha)


def _font(size: int):
    try:
        return ImageFont.load_default(size=max(8, size))
    except TypeError:  # sehr alte Pillow-Version ohne size-Parameter
        return ImageFont.load_default()


def _dashed_polyline(points, dash, closed=False):
    """Zerlegt eine (ggf. geschlossene) Punktreihe in gezeichnete Teilstuecke
    gemaess `dash` = (an_laenge, aus_laenge). Liefert eine Liste von
    (start, end)-Punktpaaren, die gezeichnet werden sollen."""
    pts = list(points) + ([points[0]] if closed else [])
    on, off = dash
    period = on + off
    pos_in_cycle = 0.0
    segments = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg_len = math.hypot(x1 - x0, y1 - y0)
        if seg_len == 0:
            continue
        ux, uy = (x1 - x0) / seg_len, (y1 - y0) / seg_len
        traveled = 0.0
        while traveled < seg_len:
            is_on = pos_in_cycle < on
            state_remaining = (on - pos_in_cycle) if is_on else (period - pos_in_cycle)
            step = min(seg_len - traveled, state_remaining)
            start = (x0 + ux * traveled, y0 + uy * traveled)
            end = (x0 + ux * (traveled + step), y0 + uy * (traveled + step))
            if is_on:
                segments.append((start, end))
            traveled += step
            pos_in_cycle = (pos_in_cycle + step) % period
    return segments


def _draw_outline(draw, points, color_rgba, width, dash, closed=True):
    if not dash:
        pts = list(points) + ([points[0]] if closed else [])
        draw.line(pts, fill=color_rgba, width=max(1, int(round(width))))
        return
    for start, end in _dashed_polyline(points, dash, closed=closed):
        draw.line([start, end], fill=color_rgba, width=max(1, int(round(width))))


def _draw_op(draw, op: shapes.DrawOp):
    if op.kind == "polygon":
        if op.fill:
            draw.polygon(op.points, fill=_hex_to_rgba(op.fill, FILL_ALPHA))
        if op.outline:
            _draw_outline(draw, op.points, _hex_to_rgba(op.outline), op.width, op.dash, closed=True)
    elif op.kind == "line":
        _draw_outline(draw, op.points, _hex_to_rgba(op.outline), op.width, op.dash, closed=False)
    elif op.kind == "text":
        x, y = op.points[0]
        draw.text((x, y), op.text, font=_font(op.font_size), fill=(0, 0, 0, 255), anchor="mm")


def _draw_calibration_points(draw, plan: TreatmentPlan, w: int, h: int):
    r = max(4, int(round(min(w, h) * 0.006)))
    for tooth, (fx, fy) in plan.calibration_points.items():
        x, y = fx * w, fy * h
        draw.ellipse((x - r, y - r, x + r, y + r), outline=CALIBRATION_COLOR, width=2)
        draw.text((x, y - r - 10), str(tooth), font=_font(int(r * 1.6)),
                   fill=CALIBRATION_COLOR, anchor="mm")


def render_plan(plan: TreatmentPlan, image: Image.Image, *, show_calibration: bool = False) -> Image.Image:
    """Zeichnet alle Positionen (und optional das Kalibrierraster) auf eine
    Kopie von `image` und liefert das kombinierte RGB-Bild zurueck."""
    base = image.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    w, h = base.size

    if show_calibration and plan.calibration_points:
        _draw_calibration_points(draw, plan, w, h)

    for item in plan.items:
        for op in shapes.build_draw_ops(item, w, h):
            _draw_op(draw, op)

    combined = Image.alpha_composite(base, overlay)
    return combined.convert("RGB")


def render_legend_strip(width_px: int, *, background=(255, 255, 255)) -> Image.Image:
    """Kleine Legende (Farbe + Bezeichnung je Befundart) als eigenstaendiges
    Bild, z. B. zum Anhaengen unter das exportierte OPG."""
    entries = shapes.legend_entries()
    swatch = max(14, width_px // 60)
    padding = swatch // 2
    cols = 2 if width_px < 900 else 4
    rows = math.ceil(len(entries) / cols)
    row_h = swatch + padding
    col_w = width_px // cols
    height = rows * row_h + padding * 2

    img = Image.new("RGB", (width_px, height), background)
    draw = ImageDraw.Draw(img)
    font = _font(swatch)

    for idx, (_kind, label, color) in enumerate(entries):
        col, row = idx % cols, idx // cols
        x = col * col_w + padding
        y = padding + row * row_h
        draw.rectangle((x, y, x + swatch, y + swatch), outline=color, width=2)
        draw.text((x + swatch + padding // 2, y + swatch / 2), label, font=font,
                   fill=(0, 0, 0), anchor="lm")
    return img


def render_plan_with_legend(plan: TreatmentPlan, image: Image.Image, *, show_calibration: bool = False) -> Image.Image:
    annotated = render_plan(plan, image, show_calibration=show_calibration)
    legend = render_legend_strip(annotated.width)
    combined = Image.new("RGB", (annotated.width, annotated.height + legend.height), (255, 255, 255))
    combined.paste(annotated, (0, 0))
    combined.paste(legend, (0, annotated.height))
    return combined
