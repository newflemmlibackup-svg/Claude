"""Symbol-Palette: eine Spalte mit den 8 Befund-Symbolen, aus der man per
Drag&Drop auf die Canvas ziehen kann."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import shapes
from .models import ALL_KINDS, KIND_BRUECKE, KIND_LABELS, PlanItem

ICON_SIZE = 46


def _icon_item(kind: str) -> PlanItem:
    if kind == KIND_BRUECKE:
        return PlanItem(kind=kind, x=0.22, y=0.5, width=0.1, height=0.05,
                         end_x=0.78, end_y=0.5, bridge_teeth=[14, 15, 16])
    aspect = shapes.DEFAULT_ASPECT.get(kind, 0.8)
    w = 0.62
    return PlanItem(kind=kind, x=0.5, y=0.5, width=w, height=w / aspect)


def _draw_icon(canvas: tk.Canvas, kind: str):
    canvas.delete("all")
    item = _icon_item(kind)
    for op in shapes.build_draw_ops(item, ICON_SIZE, ICON_SIZE):
        pts = [c for p in op.points for c in p]
        if op.kind == "polygon":
            canvas.create_polygon(pts, fill=op.fill or "", outline=op.outline or "",
                                   width=max(1.0, op.width * 0.8), dash=op.dash)
        elif op.kind == "line":
            canvas.create_line(pts, fill=op.outline, width=max(1.0, op.width * 0.8), dash=op.dash)
        # Text-Beschriftungen (z.B. "NICO/FDOK") werden im Mini-Icon
        # ausgelassen - der Symbolname steht ohnehin daneben im Palettenlabel.


class SymbolPalette(tk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.target_canvas = None
        self._drag_kind = None

        ttk.Label(self, text="Symbole", font=("Helvetica", 11, "bold")).pack(
            anchor="w", padx=6, pady=(6, 4))
        hint = ttk.Label(self, text="Ziehen Sie ein Symbol\nauf das Roentgenbild.",
                          foreground="#666", font=("Helvetica", 8))
        hint.pack(anchor="w", padx=6, pady=(0, 8))

        for kind in ALL_KINDS:
            self._build_entry(kind)

    def set_target_canvas(self, canvas):
        self.target_canvas = canvas

    def _build_entry(self, kind: str):
        row = tk.Frame(self, bd=1, relief="groove")
        row.pack(fill="x", padx=6, pady=3)

        icon = tk.Canvas(row, width=ICON_SIZE, height=ICON_SIZE, highlightthickness=0)
        icon.pack(side="left", padx=4, pady=4)
        _draw_icon(icon, kind)

        label = ttk.Label(row, text=KIND_LABELS[kind], wraplength=90, justify="left")
        label.pack(side="left", padx=4)

        for widget in (row, icon, label):
            widget.bind("<ButtonPress-1>", lambda e, k=kind: self._start_drag(k, e))
            widget.bind("<B1-Motion>", self._on_drag_motion)
            widget.bind("<ButtonRelease-1>", self._on_drag_release)

    # ------------------------------------------------------------- Drag
    def _start_drag(self, kind, _event):
        self._drag_kind = kind
        if self.target_canvas:
            self.target_canvas.begin_external_drag(kind)

    def _canvas_local(self, event):
        canvas = self.target_canvas
        return event.x_root - canvas.winfo_rootx(), event.y_root - canvas.winfo_rooty()

    def _on_drag_motion(self, event):
        if not self._drag_kind or not self.target_canvas:
            return
        lx, ly = self._canvas_local(event)
        self.target_canvas.update_external_drag(lx, ly)

    def _on_drag_release(self, event):
        if not self._drag_kind or not self.target_canvas:
            return
        lx, ly = self._canvas_local(event)
        self.target_canvas.end_external_drag(lx, ly)
        self._drag_kind = None
