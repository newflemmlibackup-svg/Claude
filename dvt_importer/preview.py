"""Kleiner Vorschau-Betrachter: blättert mit einem Regler durch die Schichten einer Aufnahme.

Gezeigt wird die Aufnahme so, wie sie später geschrieben wird - fehlende oder
unlesbare Schichten erscheinen schwarz und werden als solche gekennzeichnet.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import numpy as np

from .converter import _FrameLoader, _clean_values


def render_slice(loader, ref):
    """Rohwerte einer Schicht als 2D-Array (int64); None, wenn sie fehlt oder unlesbar ist."""
    if ref is None:
        return None
    try:
        arr, hdr, _truncated = loader.load(ref)
        data, mask = _clean_values(arr, hdr)
        if mask is not None:
            data[mask] = data[~mask].min() if (~mask).any() else 0
        return data
    except Exception:  # noqa: BLE001
        return None


def to_pgm(data, lo: float, hi: float, size: int) -> bytes:
    """Graustufenbild (PGM) der gewünschten Kantenlänge aus Rohwerten erzeugen."""
    rows, cols = data.shape
    scale = size / max(rows, cols)
    out_h, out_w = max(1, int(round(rows * scale))), max(1, int(round(cols * scale)))
    yi = np.minimum((np.arange(out_h) / scale).astype(int), rows - 1)
    xi = np.minimum((np.arange(out_w) / scale).astype(int), cols - 1)
    small = data[yi][:, xi].astype(np.float64)
    gray = np.clip((small - lo) / max(hi - lo, 1e-9) * 255.0, 0, 255).astype(np.uint8)
    return b"P5 %d %d 255\n" % (out_w, out_h) + gray.tobytes()


class PreviewPanel(ttk.Frame):
    """Bild + Regler. Mit `set_series(series)` wird eine Aufnahme geladen."""

    def __init__(self, parent, size: int = 360):
        super().__init__(parent)
        self.size = size
        self._series = None
        self._slots: list = []
        self._loader = _FrameLoader()
        self._window = (0.0, 1.0)
        self._photo = None
        self._pending = None

        self.canvas = tk.Canvas(self, width=size, height=size, background="black", highlightthickness=0)
        self.canvas.pack()
        self.scale_var = tk.DoubleVar(value=1)
        self.scale = ttk.Scale(self, from_=1, to=1, orient="horizontal", variable=self.scale_var,
                               command=self._on_slide, state="disabled")
        self.scale.pack(fill="x", pady=(6, 2))
        self.info_var = tk.StringVar(value="Keine Aufnahme ausgewählt")
        self.info = ttk.Label(self, textvariable=self.info_var, anchor="center")
        self.info.pack(fill="x")
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda _e: self.step(-1))
        self.canvas.bind("<Button-5>", lambda _e: self.step(1))

    # ------------------------------------------------------------------ API
    def set_series(self, series) -> None:
        self._series = series
        self._loader = _FrameLoader()
        self.canvas.delete("all")
        self._photo = None
        if series is None:
            self._slots = []
            self.scale.config(state="disabled", to=1)
            self.info_var.set("Keine Aufnahme ausgewählt")
            return
        self._slots = list(series.plan.slots) if series.plan is not None else list(series.slices)
        n = len(self._slots)
        self._window = self._estimate_window()
        self.scale.config(state="normal" if n > 1 else "disabled", from_=1, to=max(n, 1))
        # In der Mitte beginnen - aber möglichst bei einer vorhandenen Schicht.
        present = [i for i, ref in enumerate(self._slots) if ref is not None]
        self.show(min(present, key=lambda i: abs(i - n // 2)) if present else 0)

    @property
    def index(self) -> int:
        return int(round(self.scale_var.get())) - 1

    def step(self, delta: int) -> None:
        if self._slots:
            self.show(min(max(self.index + delta, 0), len(self._slots) - 1))

    def show(self, index: int) -> None:
        if not self._slots:
            return
        index = min(max(index, 0), len(self._slots) - 1)
        self.scale_var.set(index + 1)
        ref = self._slots[index]
        data = render_slice(self._loader, ref)
        text = f"Schicht {index + 1} von {len(self._slots)}"
        self.canvas.delete("all")
        if data is None:
            self._photo = None
            reason = "fehlt" if ref is None else "ist nicht lesbar"
            self.canvas.create_text(self.size // 2, self.size // 2, fill="#ff8a65", width=self.size - 40,
                                    justify="center", font=("", 12, "bold"),
                                    text=f"Diese Schicht {reason}.\nSie wird schwarz ersetzt.")
            text += f"  –  {reason}"
        else:
            lo, hi = self._window
            try:
                self._photo = tk.PhotoImage(data=to_pgm(data, lo, hi, self.size), format="ppm")
                self.canvas.create_image(self.size // 2, self.size // 2, image=self._photo)
            except tk.TclError:
                self.canvas.create_text(self.size // 2, self.size // 2, fill="white",
                                        text="Vorschau nicht möglich")
        self.info_var.set(text)

    # --------------------------------------------------------------- intern
    def _estimate_window(self) -> tuple:
        """Helligkeitsbereich aus einigen Stichproben - bleibt beim Blättern gleich."""
        real = [s for s in self._slots if s is not None]
        samples = []
        for ref in real[:: max(1, len(real) // 5)][:6]:
            data = render_slice(self._loader, ref)
            if data is not None:
                samples.append(data[::4, ::4].ravel())
        if not samples:
            return 0.0, 1.0
        values = np.concatenate(samples)
        lo, hi = np.percentile(values, [1.0, 99.8])
        return float(lo), float(hi if hi > lo else lo + 1)

    def _on_slide(self, _value=None):
        if self._pending is None:
            self._pending = self.after(15, self._apply_slide)

    def _apply_slide(self):
        self._pending = None
        self.show(self.index)

    def _on_wheel(self, event):
        self.step(-1 if event.delta > 0 else 1)


def open_preview_window(parent, series) -> tk.Toplevel:
    win = tk.Toplevel(parent)
    win.title(f"Vorschau – {series.patient.display_name}")
    win.resizable(False, False)
    panel = PreviewPanel(win, size=512)
    panel.pack(padx=12, pady=(12, 6))
    ttk.Label(win, text="Regler bewegen oder Mausrad drehen, um durch die Schichten zu blättern.",
              foreground="#666666").pack(pady=(0, 10))
    panel.set_series(series)
    win.transient(parent)
    return win
