"""Symbol-Palette: Kacheln mit Vorschau der echten Symbolkontur.

Zwei gleichwertige Wege, ein Symbol zu setzen:

* Ziehen  - Kachel anfassen und auf das Roentgenbild ziehen; waehrend des
            Ziehens zeigt die Canvas die spaetere Kontur in Zielgroesse.
* Klicken - Kachel einmal anklicken (sie bleibt aktiv markiert), dann die
            Stelle im Bild anklicken. Fuer Trackpads oft angenehmer als ein
            langer Ziehweg ueber den Bildschirm.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import shapes, theme
from .models import ALL_KINDS, KIND_BRUECKE, KIND_LABELS, PlanItem

ICON_SIZE = 34
TILE_PAD = 5


def _icon_item(kind: str) -> PlanItem:
    if kind == KIND_BRUECKE:
        return PlanItem(kind=kind, x=0.18, y=0.5, width=0.1, height=0.12,
                        end_x=0.82, end_y=0.5, bridge_teeth=[14, 15, 16])
    aspect = shapes.aspect_for(kind)
    # Ins Icon-Quadrat einpassen: die laengere Achse bestimmt den Massstab.
    if aspect >= 1.0:
        w = 0.80
        h = w / aspect
    else:
        h = 0.86
        w = h * aspect
    return PlanItem(kind=kind, x=0.5, y=0.5, width=w, height=h)


def draw_symbol_icon(canvas: tk.Canvas, kind: str, size: int = ICON_SIZE) -> None:
    """Zeichnet die Symbolkontur formatfuellend in ein kleines Canvas."""
    canvas.delete("all")
    item = _icon_item(kind)
    for op in shapes.build_draw_ops(item, size, size):
        pts = [c for p in op.points for c in p]
        if op.kind == "polygon":
            canvas.create_polygon(pts, fill=op.fill or "", outline=op.outline or "",
                                   width=max(1.0, op.width * 0.7), dash=op.dash)
        elif op.kind == "line":
            canvas.create_line(pts, fill=op.outline, width=max(1.0, op.width * 0.7),
                                dash=op.dash)
        # Text-Beschriftungen werden im Mini-Icon ausgelassen - der Symbolname
        # steht ohnehin direkt daneben.


class SymbolPalette(tk.Frame):
    def __init__(self, parent, **kwargs):
        kwargs.setdefault("bg", theme.BG_APP)
        super().__init__(parent, **kwargs)
        self.target_canvas = None
        self.on_armed_change = None

        self._drag_kind = None
        self._dragging = False
        self._armed_kind = None
        self._tiles = {}

        header = tk.Frame(self, bg=theme.BG_APP)
        header.pack(fill="x", padx=theme.PAD_MD, pady=(theme.PAD_MD, 2))
        ttk.Label(header, text="Befunde", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(header, text="Ziehen – oder anklicken\nund ins Bild klicken.",
                  style="Muted.TLabel", justify="left").pack(anchor="w", pady=(2, 0))

        body = tk.Frame(self, bg=theme.BG_APP)
        body.pack(fill="both", expand=True, padx=theme.PAD_SM, pady=(theme.PAD_SM, 0))
        for kind in ALL_KINDS:
            self._build_tile(body, kind)

    def set_target_canvas(self, canvas):
        self.target_canvas = canvas

    # ------------------------------------------------------------- Kacheln
    def _build_tile(self, parent, kind: str):
        tile = theme.card(parent)
        tile.pack(fill="x", pady=2)

        icon = tk.Canvas(tile, width=ICON_SIZE, height=ICON_SIZE, highlightthickness=0,
                          bg=theme.BG_SURFACE, cursor="hand2")
        icon.pack(side="left", padx=(TILE_PAD, TILE_PAD), pady=TILE_PAD)
        draw_symbol_icon(icon, kind)

        label = tk.Label(tile, text=KIND_LABELS[kind], bg=theme.BG_SURFACE,
                          fg=theme.TEXT, font=theme.Fonts.label, anchor="w",
                          justify="left", wraplength=150, cursor="hand2")
        label.pack(side="left", fill="x", expand=True, padx=(0, TILE_PAD))

        widgets = (tile, icon, label)
        self._tiles[kind] = widgets

        for widget in widgets:
            widget.bind("<ButtonPress-1>", lambda e, k=kind: self._on_press(k, e))
            widget.bind("<B1-Motion>", lambda e, k=kind: self._on_motion(k, e))
            widget.bind("<ButtonRelease-1>", lambda e, k=kind: self._on_release(k, e))
            widget.bind("<Enter>", lambda e, k=kind: self._set_tile_bg(k, hover=True))
            widget.bind("<Leave>", lambda e, k=kind: self._set_tile_bg(k, hover=False))

    def _set_tile_bg(self, kind, *, hover: bool):
        if kind == self._armed_kind:
            return  # aktive Kachel behaelt ihre Hervorhebung
        color = theme.BG_SUBTLE if hover else theme.BG_SURFACE
        self._paint_tile(kind, color, theme.BORDER)

    def _paint_tile(self, kind, bg, border):
        tile, icon, label = self._tiles[kind]
        tile.configure(bg=bg, highlightbackground=border, highlightcolor=border)
        icon.configure(bg=bg)
        label.configure(bg=bg)

    # ---------------------------------------------------- Aktive Auswahl
    @property
    def armed_kind(self):
        """Per Klick vorgemerkte Befundart (oder None)."""
        return self._armed_kind

    def set_armed(self, kind):
        previous = self._armed_kind
        self._armed_kind = kind
        if previous and previous in self._tiles:
            self._paint_tile(previous, theme.BG_SURFACE, theme.BORDER)
        if kind and kind in self._tiles:
            self._paint_tile(kind, theme.ACCENT_SOFT, theme.ACCENT)
        if self.on_armed_change:
            self.on_armed_change(kind)

    def clear_armed(self):
        self.set_armed(None)

    # ------------------------------------------------------------- Ziehen
    def _canvas_local(self, event):
        canvas = self.target_canvas
        return (event.x_root - canvas.winfo_rootx(),
                event.y_root - canvas.winfo_rooty())

    def _on_press(self, kind, _event):
        self._drag_kind = kind
        self._dragging = False

    def _on_motion(self, kind, event):
        if self._drag_kind != kind or not self.target_canvas:
            return
        if not self._dragging:
            # Erst ab einer echten Mausbewegung als Ziehen werten - sonst
            # loest schon ein Klick mit minimalem Wackeln einen Drag aus.
            self._dragging = True
            self.set_armed(None)
            self.target_canvas.begin_external_drag(kind)
        self.target_canvas.update_external_drag(*self._canvas_local(event))

    def _on_release(self, kind, event):
        if self._drag_kind != kind or not self.target_canvas:
            self._drag_kind = None
            return
        if self._dragging:
            self.target_canvas.end_external_drag(*self._canvas_local(event))
        else:
            # Reiner Klick: Befundart vormerken bzw. Auswahl wieder aufheben.
            self.set_armed(None if self._armed_kind == kind else kind)
        self._drag_kind = None
        self._dragging = False
