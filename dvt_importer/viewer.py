"""Notfall-Viewer: einfache DVT-Betrachtung im Stil der üblichen Dental-Software.

Gedacht für den Fall, dass eine Aufnahme hier gelesen werden kann, sich aber
(noch) nicht in Sidexis importieren lässt. Funktionen:

  * drei Schnittebenen (axial, koronal, sagittal) mit gekoppeltem Fadenkreuz
  * 3D-Ansicht (Oberfläche oder Röntgen-Durchleuchtung), mit der Maus drehbar
  * Panorama-Rekonstruktion entlang einer selbst gezeichneten Kieferkurve
  * Blättern, Zoom, Verschieben, Helligkeit/Kontrast, Schichtdicke
  * Strecken- und Winkelmessung in Millimetern bzw. Grad

Alles läuft in reinem Python mit numpy und Tkinter - ohne Grafikkarte oder
Zusatzbibliotheken, damit es auch in der fertig gebauten Anwendung funktioniert.
Kein zertifiziertes Medizinprodukt: nur zur Ansicht im Notfall.
"""
from __future__ import annotations

import math
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np

from .converter import _FrameLoader
from .preview import render_slice

AX, COR, SAG, PAN, V3D = "axial", "coronal", "sagittal", "panorama", "3d"
TITLES = {AX: "Axial", COR: "Koronal", SAG: "Sagittal", PAN: "Panorama", V3D: "3D"}
COLORS = {AX: "#4dabf7", COR: "#51cf66", SAG: "#ff6b6b", PAN: "#fcc419", V3D: "#ced4da"}
BG = "#0f1215"
PANEL_BG = "#1a1e23"
FG = "#e9ecef"
MUTED = "#8b949e"
MEASURE = "#ffd43b"
CURVE = "#fcc419"

TOOLS = (
    ("navigate", "✛  Fadenkreuz",
     "Klicken: Fadenkreuz setzen · Mausrad: durch die Schichten blättern · Doppelklick: Ansicht groß/klein"),
    ("pan", "✥  Verschieben", "Ziehen: Bild verschieben"),
    ("zoom", "⊕  Zoom", "Ziehen nach oben/unten: vergrößern/verkleinern (auch Strg + Mausrad)"),
    ("window", "◐  Helligkeit", "Ziehen: links/rechts = Kontrast, hoch/runter = Helligkeit "
                                "(geht jederzeit auch mit der rechten Maustaste)"),
    ("distance", "↔  Strecke", "Klicken und ziehen: Strecke in mm messen"),
    ("angle", "∠  Winkel", "Drei Punkte anklicken (Scheitelpunkt als zweiten): Winkel messen"),
    ("curve", "⌒  Panoramakurve", "In der AXIALEN Ansicht entlang des Zahnbogens klicken (von einer Seite "
                                  "zur anderen), Doppelklick beendet – rechts unten erscheint das Panorama"),
)
SLABS = (("dünn (1 Schicht)", 0.0), ("1 mm", 1.0), ("3 mm", 3.0), ("5 mm", 5.0), ("10 mm", 10.0))
WINDOW_PRESETS = ("Automatisch", "Knochen / Zähne", "Weichgewebe", "Kontrastreich")


class ViewerCancelled(Exception):
    pass


# ============================================================== Volumendaten
class VolumeData:
    """Das komplette Volumen im Speicher. Achsen (Z, Y, X); Z steigt nach kranial."""

    def __init__(self, vol: np.ndarray, spacing: tuple, missing: list, label: str):
        self.vol = vol
        self.spacing = tuple(float(s) for s in spacing)   # (sz, sy, sx) in mm
        self.missing = set(missing)
        self.label = label
        step = max(1, vol.shape[0] // 64)
        sample = vol[::step, ::4, ::4]
        self.lo, self.hi = (float(v) for v in np.percentile(sample, [1.0, 99.8]))
        if self.hi <= self.lo:
            self.hi = self.lo + 1.0
        self.vmin = float(vol.min())
        self._small = None

    @property
    def shape(self) -> tuple:
        return self.vol.shape

    # ----------------------------------------------------------- Laden
    @classmethod
    def load(cls, series, progress=None, cancelled=None) -> "VolumeData":
        plan = series.plan
        slots = list(plan.slots) if plan is not None else list(series.slices)
        if plan is not None:
            spacing = (plan.slice_spacing, plan.pixel_spacing[0], plan.pixel_spacing[1])
            if plan.step[2] < 0:            # erste Schicht liegt oben -> umdrehen
                slots = slots[::-1]
        else:
            spacing = (1.0, 1.0, 1.0)
        rows, cols = series.rows, series.columns
        loader = _FrameLoader()
        vol = None
        missing = []
        for i, ref in enumerate(slots):
            if cancelled is not None and cancelled():
                raise ViewerCancelled()
            data = render_slice(loader, ref)
            if data is None or data.shape != (rows, cols):
                missing.append(i)
            else:
                if vol is None:
                    lo, hi = int(data.min()), int(data.max())
                    if lo >= -32768 and hi <= 32767:
                        dtype = np.int16
                    elif lo >= 0 and hi <= 65535:
                        dtype = np.uint16
                    else:
                        dtype = np.int32
                    vol = np.zeros((len(slots), rows, cols), dtype=dtype)
                info = np.iinfo(vol.dtype)
                vol[i] = np.clip(data, info.min, info.max)
            if progress is not None:
                progress(i + 1, len(slots))
        if vol is None:
            raise ValueError("Keine einzige Schicht dieser Aufnahme ist lesbar.")
        if missing:
            present = np.ones(len(slots), dtype=bool)
            present[missing] = False
            vol[missing] = vol[present].min()
        return cls(vol, spacing, missing, series.patient.display_name)

    # ---------------------------------------------------- Schnittebenen
    @staticmethod
    def _half(slab_mm: float, spacing: float) -> int:
        return max(0, int(round(slab_mm / spacing / 2.0)))

    def plane(self, kind: str, index: int, slab_mm: float = 0.0):
        """2D-Bild (Zeile 0 oben) und Pixelabstände (Zeile, Spalte) in mm."""
        sz, sy, sx = self.spacing
        if kind == AX:
            n = self._half(slab_mm, sz)
            block = self.vol[max(0, index - n):index + n + 1]
            img = block[0] if block.shape[0] == 1 else block.mean(axis=0, dtype=np.float32)
            return img, (sy, sx)
        if kind == COR:
            n = self._half(slab_mm, sy)
            block = self.vol[:, max(0, index - n):index + n + 1, :]
            img = block[:, 0, :] if block.shape[1] == 1 else block.mean(axis=1, dtype=np.float32)
            return img[::-1], (sz, sx)
        if kind == SAG:
            n = self._half(slab_mm, sx)
            block = self.vol[:, :, max(0, index - n):index + n + 1]
            img = block[:, :, 0] if block.shape[2] == 1 else block.mean(axis=2, dtype=np.float32)
            return img[::-1], (sz, sy)
        raise ValueError(kind)

    def value_at(self, z: int, y: int, x: int) -> float:
        Z, Y, X = self.vol.shape
        return float(self.vol[min(max(z, 0), Z - 1), min(max(y, 0), Y - 1), min(max(x, 0), X - 1)])

    # ---------------------------------------------------------- Panorama
    def curve_path(self, points_vox: list) -> tuple:
        """Glatte Kurve durch die Klickpunkte (Voxel x/y der axialen Ebene).

        Liefert Punkte im Abstand eines Pixels (in mm) und die Normalen dazu."""
        sz, sy, sx = self.spacing
        pts = np.array([(p[0] * sx, p[1] * sy) for p in points_vox], dtype=np.float64)
        if len(pts) < 2:
            raise ValueError("Mindestens zwei Punkte nötig")
        if len(pts) == 2:
            dense = np.linspace(pts[0], pts[1], 200)
        else:   # Catmull-Rom-Spline
            ext = np.vstack([pts[0], pts, pts[-1]])
            segs = []
            for i in range(1, len(ext) - 2):
                p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
                t = np.linspace(0, 1, 40, endpoint=False)[:, None]
                segs.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2
                                   + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
            segs.append(pts[-1][None])
            dense = np.vstack(segs)
        seg_len = np.hypot(*np.diff(dense, axis=0).T)
        arc = np.concatenate([[0.0], np.cumsum(seg_len)])
        step = min(sy, sx)
        if arc[-1] < step:
            raise ValueError("Kurve zu kurz")
        s = np.arange(0.0, arc[-1], step)
        path = np.column_stack([np.interp(s, arc, dense[:, 0]), np.interp(s, arc, dense[:, 1])])
        tangent = np.gradient(path, axis=0)
        tangent /= np.maximum(np.hypot(tangent[:, 0], tangent[:, 1])[:, None], 1e-9)
        normal = np.column_stack([-tangent[:, 1], tangent[:, 0]])
        # Normale nach außen (weg vom Mittelpunkt des Bogens) ausrichten
        centre = path.mean(axis=0)
        if np.mean(np.sum((path - centre) * normal, axis=1)) < 0:
            normal = -normal
        return path, normal, step

    def panorama(self, points_vox: list, offset_mm: float = 0.0, thickness_mm: float = 8.0):
        """Panoramaschicht entlang der Kurve, gemittelt über `thickness_mm`.

        Rückgabe: Bild (Zeile 0 = kranial), Pixelabstände (Zeile, Spalte), Mittellinie (mm)."""
        sz, sy, sx = self.spacing
        Z, Y, X = self.vol.shape
        path, normal, step = self.curve_path(points_vox)
        base = path + normal * offset_mm
        k = np.arange(-thickness_mm / 2.0, thickness_mm / 2.0 + 1e-6, step) if thickness_mm > step else np.array([0.0])
        px = (base[:, 0, None] + normal[:, 0, None] * k[None, :]) / sx    # (S, K)
        py = (base[:, 1, None] + normal[:, 1, None] * k[None, :]) / sy
        xi, yi = np.floor(px).astype(np.int64), np.floor(py).astype(np.int64)
        inside = (xi >= 0) & (xi < X) & (yi >= 0) & (yi < Y)
        xi, yi = np.clip(xi, 0, X - 1), np.clip(yi, 0, Y - 1)
        img = np.empty((Z, len(base)), dtype=np.float32)
        weight = np.maximum(inside.sum(axis=1), 1)
        for z0 in range(0, Z, 64):         # in Blöcken, damit der Speicher klein bleibt
            vals = self.vol[z0:z0 + 64][:, yi, xi].astype(np.float32)          # (z, S, K)
            vals = np.where(inside[None], vals, 0.0)
            img[z0:z0 + 64] = vals.sum(axis=2) / weight[None]
        img[:, inside.sum(axis=1) == 0] = self.vmin
        return img[::-1], (sz, step), base

    # ---------------------------------------------------------------- 3D
    def small(self, target: int = 160) -> tuple:
        """Verkleinertes, ungefähr würfelförmig abgetastetes Volumen für die 3D-Ansicht."""
        if self._small is None:
            sz, sy, sx = self.spacing
            Z, Y, X = self.vol.shape
            ext = (Z * sz, Y * sy, X * sx)
            step = max(ext) / target
            # 1) blockweise mitteln (glättet das Rauschen), 2) auf Zielgröße abtasten, 3) leicht weichzeichnen
            factors = [max(1, int(step / sp)) for sp in (sz, sy, sx)]
            fz, fy, fx = factors
            nz, ny, nx = Z // fz, Y // fy, X // fx
            block = self.vol[:nz * fz, :ny * fy, :nx * fx].astype(np.float32)
            block = block.reshape(nz, fz, ny, fy, nx, fx).mean(axis=(1, 3, 5))
            idx = [np.linspace(0, n - 1, max(2, int(round(e / step)))).round().astype(np.int64)
                   for n, e in zip(block.shape, ext)]
            small = block[idx[0]][:, idx[1]][:, :, idx[2]]
            small = _box_blur(small)
            self._small = (np.ascontiguousarray(small, dtype=np.float32), step)
        return self._small

    def render3d(self, azimuth: float, elevation: float, size: int, mode: str, threshold: float,
                 zoom: float = 1.0) -> np.ndarray:
        """Software-Raycasting. Rückgabe: RGB-Bild (size, size, 3) uint8."""
        vol, _step = self.small()
        D, H, W = vol.shape
        flat = vol.ravel()
        centre = np.array([(W - 1) / 2.0, (H - 1) / 2.0, (D - 1) / 2.0])
        ca, sa, ce, se = math.cos(azimuth), math.sin(azimuth), math.cos(elevation), math.sin(elevation)
        # Patientenachsen: x nach links, y nach hinten, z nach oben. Azimut 0 = Blick von vorn.
        d = np.array([sa * ce, ca * ce, -se])
        u = np.array([ca, -sa, 0.0])
        v = np.cross(d, u)
        radius = 0.5 * math.sqrt(W * W + H * H + D * D)
        half = radius / zoom
        samples = int(2 * radius) + 1
        s = np.linspace(-half, half, size, dtype=np.float32)
        t = np.linspace(-radius, radius, samples, dtype=np.float32)
        out = np.zeros((size, size), dtype=np.float32)
        depth = np.full((size, size), np.inf, dtype=np.float32)
        rows_per_chunk = max(1, 3_000_000 // (size * samples))
        for r0 in range(0, size, rows_per_chunk):
            sv = s[r0:r0 + rows_per_chunk][:, None, None]
            su = s[None, :, None]
            tt = t[None, None, :]
            coords = []
            for axis in range(3):
                coords.append(np.rint(centre[axis] + su * u[axis] + sv * v[axis] + tt * d[axis]).astype(np.int32))
            xi, yi, zi = coords
            inside = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H) & (zi >= 0) & (zi < D)
            lin = (np.clip(zi, 0, D - 1) * H + np.clip(yi, 0, H - 1)) * W + np.clip(xi, 0, W - 1)
            vals = np.where(inside, flat[lin], -np.inf)
            if mode == "mip":
                out[r0:r0 + rows_per_chunk] = vals.max(axis=2)
            else:
                hit = vals >= threshold
                has = hit.any(axis=2)
                first = np.argmax(hit, axis=2).astype(np.float32)
                depth[r0:r0 + rows_per_chunk] = np.where(has, first, np.inf)
        if mode == "mip":
            lo, hi = self.lo, self.hi
            gray = np.clip((out - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)
            return np.repeat(gray[:, :, None], 3, axis=2)
        # Oberfläche: Licht aus der Tiefenkarte berechnen
        has = np.isfinite(depth)
        if not has.any():
            return np.zeros((size, size, 3), dtype=np.uint8)
        dfill = np.where(has, depth, np.nanmax(np.where(has, depth, np.nan)))
        dfill = _box_blur2d(dfill)
        pixel = 2.0 * half / size
        sample_step = 2.0 * radius / (samples - 1)
        dz = dfill * sample_step
        gy, gx = np.gradient(dz, pixel)
        gx, gy = np.clip(gx, -4, 4), np.clip(gy, -4, 4)
        norm = np.sqrt(gx * gx + gy * gy + 1.0)
        light = np.array([-0.35, -0.55, -1.0])
        light /= np.linalg.norm(light)
        lambert = np.clip((gx * light[0] + gy * light[1] - light[2]) / norm, 0, 1)
        dmin, dmax = dz[has].min(), dz[has].max()
        cue = 1.0 - 0.45 * (dz - dmin) / max(dmax - dmin, 1e-6)
        shade = (0.18 + 0.82 * lambert) * cue
        colour = np.array([255, 244, 222], dtype=np.float32)
        rgb = shade[:, :, None] * colour[None, None, :]
        rgb[~has] = (15, 18, 21)
        return np.clip(rgb, 0, 255).astype(np.uint8)


# ================================================================ Hilfsfunktionen
def _box_blur(vol: np.ndarray) -> np.ndarray:
    """3er-Mittelwert entlang jeder Achse (einfacher, schneller Weichzeichner)."""
    out = vol
    for axis in range(vol.ndim):
        padded = np.pad(out, [(1, 1) if a == axis else (0, 0) for a in range(vol.ndim)], mode="edge")
        sl = [slice(None)] * vol.ndim
        parts = []
        for start in range(3):
            sl[axis] = slice(start, start + out.shape[axis])
            parts.append(padded[tuple(sl)])
        out = (parts[0] + parts[1] + parts[2]) / 3.0
    return out


def _box_blur2d(img: np.ndarray) -> np.ndarray:
    return _box_blur(img)


def to_photo_data(gray: np.ndarray) -> bytes:
    if gray.ndim == 2:
        return b"P5 %d %d 255\n" % (gray.shape[1], gray.shape[0]) + gray.tobytes()
    return b"P6 %d %d 255\n" % (gray.shape[1], gray.shape[0]) + gray.tobytes()


def apply_window(img: np.ndarray, centre: float, width: float) -> np.ndarray:
    lo = centre - width / 2.0
    return np.clip((img.astype(np.float32) - lo) * (255.0 / max(width, 1e-6)), 0, 255).astype(np.uint8)


def wheel_steps(event) -> int:
    if getattr(event, "num", None) == 4:
        return 1
    if getattr(event, "num", None) == 5:
        return -1
    return 1 if event.delta > 0 else -1


def distance_mm(p, q) -> float:
    return math.hypot(q[0] - p[0], q[1] - p[1])


def angle_deg(a, vertex, b) -> float:
    v1 = (a[0] - vertex[0], a[1] - vertex[1])
    v2 = (b[0] - vertex[0], b[1] - vertex[1])
    n1, n2 = math.hypot(*v1), math.hypot(*v2)
    if n1 < 1e-9 or n2 < 1e-9:
        return 0.0
    cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.degrees(math.acos(cos))


# ==================================================================== 2D-Ansicht
class SlicePanel(tk.Frame):
    """Eine 2D-Ansicht mit Kopfzeile, Bildfläche und Schieberegler."""

    def __init__(self, viewer: "ViewerWindow", parent, kind: str, header=True):
        super().__init__(parent, background=PANEL_BG)
        self.viewer = viewer
        self.kind = kind
        self.zoom = 1.0
        self.pan = [0.0, 0.0]
        self._photo = None
        self._geom = None             # (ox, oy, scale, rows, cols, ry, rx)
        self._drag = None
        self._pending = False
        self._slider_lock = False

        if header:
            self.header = tk.Frame(self, background=PANEL_BG)
            self.header.pack(fill="x")
            tk.Frame(self.header, background=COLORS[kind], width=6).pack(side="left", fill="y")
            tk.Label(self.header, text=TITLES[kind], background=PANEL_BG, foreground=FG,
                     font=("", 11, "bold")).pack(side="left", padx=6, pady=3)
            self.pos_label = tk.Label(self.header, text="", background=PANEL_BG, foreground=MUTED, font=("", 10))
            self.pos_label.pack(side="right", padx=8)
        else:
            self.pos_label = None
        self.canvas = tk.Canvas(self, background="black", highlightthickness=2,
                                highlightbackground=PANEL_BG, highlightcolor=PANEL_BG, width=200, height=200)
        self.canvas.pack(fill="both", expand=True)
        self.slider = ttk.Scale(self, orient="horizontal", from_=0, to=1, command=self._on_slider)
        self.slider.pack(fill="x", padx=4, pady=(2, 4))

        c = self.canvas
        c.bind("<Configure>", lambda _e: self.schedule())
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._motion_drag)
        c.bind("<ButtonRelease-1>", self._release)
        c.bind("<Double-Button-1>", self._double)
        for b in ("2", "3"):
            c.bind(f"<ButtonPress-{b}>", self._wl_press)
            c.bind(f"<B{b}-Motion>", self._wl_drag)
        c.bind("<Control-ButtonPress-1>", self._wl_press)   # macOS: Ctrl-Klick = Rechtsklick
        c.bind("<Control-B1-Motion>", self._wl_drag)
        c.bind("<MouseWheel>", self._wheel)
        c.bind("<Control-MouseWheel>", lambda e: self._zoom_by(1.1 if wheel_steps(e) > 0 else 1 / 1.1))
        c.bind("<Button-4>", self._wheel)
        c.bind("<Button-5>", self._wheel)
        c.bind("<Motion>", self._hover)
        c.bind("<Enter>", lambda _e: self.viewer.set_active(self))

    # -------------------------------------------------------- Daten
    def image(self):
        data = self.viewer.data
        return data.plane(self.kind, self.index, self.viewer.slab_mm)

    @property
    def index(self) -> int:
        z, y, x = self.viewer.cursor
        return {AX: z, COR: y, SAG: x}[self.kind]

    @property
    def count(self) -> int:
        Z, Y, X = self.viewer.data.shape
        return {AX: Z, COR: Y, SAG: X}[self.kind]

    def set_index(self, value: int) -> None:
        value = int(min(max(value, 0), self.count - 1))
        z, y, x = self.viewer.cursor
        if self.kind == AX:
            z = value
        elif self.kind == COR:
            y = value
        else:
            x = value
        self.viewer.set_cursor(z, y, x)

    def scroll(self, steps: int) -> None:
        # Mausrad nach oben = kranial (axial) bzw. nach vorn/rechts
        self.set_index(self.index + steps)

    def position_text(self) -> str:
        return f"{self.index + 1} / {self.count}"

    # cursor in Bild-mm (x nach rechts, y nach unten)
    def cursor_mm(self):
        sz, sy, sx = self.viewer.data.spacing
        Z = self.viewer.data.shape[0]
        z, y, x = self.viewer.cursor
        if self.kind == AX:
            return (x + 0.5) * sx, (y + 0.5) * sy
        if self.kind == COR:
            return (x + 0.5) * sx, (Z - 1 - z + 0.5) * sz
        return (y + 0.5) * sy, (Z - 1 - z + 0.5) * sz

    def set_cursor_from_mm(self, mx: float, my: float) -> None:
        sz, sy, sx = self.viewer.data.spacing
        Z, Y, X = self.viewer.data.shape
        z, y, x = self.viewer.cursor
        if self.kind == AX:
            x, y = int(mx // sx), int(my // sy)
        elif self.kind == COR:
            x, z = int(mx // sx), Z - 1 - int(my // sz)
        else:
            y, z = int(mx // sy), Z - 1 - int(my // sz)
        self.viewer.set_cursor(min(max(z, 0), Z - 1), min(max(y, 0), Y - 1), min(max(x, 0), X - 1))

    def voxel_from_mm(self, mx: float, my: float):
        sz, sy, sx = self.viewer.data.spacing
        Z = self.viewer.data.shape[0]
        z, y, x = self.viewer.cursor
        if self.kind == AX:
            return z, int(my // sy), int(mx // sx)
        if self.kind == COR:
            return Z - 1 - int(my // sz), y, int(mx // sx)
        return Z - 1 - int(my // sz), int(mx // sy), x

    # ---------------------------------------------------- Abbildung
    def canvas_to_mm(self, cx: float, cy: float):
        ox, oy, scale = self._geom[:3]
        return (cx - ox) / scale, (cy - oy) / scale

    def mm_to_canvas(self, mx: float, my: float):
        ox, oy, scale = self._geom[:3]
        return ox + mx * scale, oy + my * scale

    def schedule(self) -> None:
        if not self._pending:
            self._pending = True
            self.after_idle(self._redraw)

    def _redraw(self) -> None:
        self._pending = False
        if self.viewer.data is None or not self.winfo_exists():
            return
        W, H = max(self.canvas.winfo_width() - 4, 10), max(self.canvas.winfo_height() - 4, 10)
        self.canvas.delete("all")
        try:
            img, (ry, rx) = self.image()
        except Exception as exc:  # noqa: BLE001
            self.canvas.create_text(W // 2, H // 2, text=str(exc), fill=MUTED, width=W - 40)
            self._geom = None
            return
        rows, cols = img.shape
        w_mm, h_mm = cols * rx, rows * ry
        scale = min(W / w_mm, H / h_mm) * self.zoom
        ox = W / 2 + self.pan[0] - w_mm * scale / 2 + 2
        oy = H / 2 + self.pan[1] - h_mm * scale / 2 + 2
        self._geom = (ox, oy, scale, rows, cols, ry, rx)
        # Bildpunkte für jedes Bildschirm-Pixel ermitteln (nächster Nachbar)
        xs = (np.arange(W) + 2.5 - ox) / scale / rx
        ys = (np.arange(H) + 2.5 - oy) / scale / ry
        ci, ri = np.floor(xs).astype(np.int64), np.floor(ys).astype(np.int64)
        cv, rv = (ci >= 0) & (ci < cols), (ri >= 0) & (ri < rows)
        x0, x1 = (np.argmax(cv), len(cv) - np.argmax(cv[::-1])) if cv.any() else (0, 0)
        y0, y1 = (np.argmax(rv), len(rv) - np.argmax(rv[::-1])) if rv.any() else (0, 0)
        if x1 > x0 and y1 > y0:
            part = img[np.ix_(ri[y0:y1], ci[x0:x1])]
            gray = apply_window(part, *self.viewer.window)
            self._photo = tk.PhotoImage(data=to_photo_data(np.ascontiguousarray(gray)), format="ppm")
            self.canvas.create_image(x0 + 2, y0 + 2, image=self._photo, anchor="nw")
        self._draw_overlays(W, H)
        if self.pos_label is not None:
            self.pos_label.config(text=self.position_text())
        self._slider_lock = True
        self.slider.configure(to=max(self.count - 1, 1))
        self.slider.set(self.index)
        self._slider_lock = False

    def _draw_overlays(self, W, H) -> None:
        c = self.canvas
        active = self.viewer.active is self
        c.configure(highlightbackground=COLORS[self.kind] if active else PANEL_BG,
                    highlightcolor=COLORS[self.kind] if active else PANEL_BG)
        # Fadenkreuz
        if self.viewer.show_crosshair:
            mx, my = self.cursor_mm()
            cx, cy = self.mm_to_canvas(mx, my)
            vertical, horizontal = {AX: (SAG, COR), COR: (SAG, AX), SAG: (COR, AX)}[self.kind]
            c.create_line(cx, 0, cx, H + 4, fill=COLORS[vertical], dash=(6, 4))
            c.create_line(0, cy, W + 4, cy, fill=COLORS[horizontal], dash=(6, 4))
        # Orientierung
        left, right, top, bottom = {AX: ("R", "L", "A", "P"), COR: ("R", "L", "S", "I"),
                                    SAG: ("A", "P", "S", "I")}.get(self.kind, ("", "", "", ""))
        for text, x, y, anchor in ((left, 8, H / 2, "w"), (right, W - 4, H / 2, "e"),
                                   (top, W / 2, 8, "n"), (bottom, W / 2, H - 2, "s")):
            if text:
                c.create_text(x, y, text=text, fill=MUTED, font=("", 11, "bold"), anchor=anchor)
        if self.kind == AX:
            z = self.viewer.cursor[0]
            if z in self.viewer.data.missing:
                c.create_text(W / 2, 30, text="Diese Schicht fehlte – schwarz ergänzt", fill="#ff8a65",
                              font=("", 11, "bold"))
            self._draw_curve()
        self._draw_measurements()

    def _draw_curve(self) -> None:
        points = self.viewer.curve_points
        if not points:
            return
        sz, sy, sx = self.viewer.data.spacing
        coords = [self.mm_to_canvas((x + 0.5) * sx, (y + 0.5) * sy) for x, y in points]
        if len(points) >= 2:
            try:
                path, _n, _s = self.viewer.data.curve_path(points)
                line = [self.mm_to_canvas(px + sx / 2, py + sy / 2) for px, py in path[:: max(1, len(path) // 200)]]
                self.canvas.create_line(*[v for p in line for v in p], fill=CURVE, width=2, smooth=True)
            except ValueError:
                pass
        for cx, cy in coords:
            self.canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, outline=CURVE, width=2)

    def measurement_key(self):
        return self.kind, self.index

    def _draw_measurements(self) -> None:
        c = self.canvas
        key = self.measurement_key()
        items = [m for m in self.viewer.measurements if m["key"] == key]
        if self.viewer.pending is not None and self.viewer.pending["key"] == key:
            items.append(self.viewer.pending)
        for m in items:
            pts = [self.mm_to_canvas(*p) for p in m["pts"]]
            if len(pts) >= 2:
                c.create_line(*[v for p in pts for v in p], fill=MEASURE, width=2)
            for x, y in pts:
                c.create_oval(x - 3, y - 3, x + 3, y + 3, fill=MEASURE, outline="")
            text = None
            if m["kind"] == "distance" and len(m["pts"]) == 2:
                text = f"{distance_mm(*m['pts']):.1f} mm"
            elif m["kind"] == "angle" and len(m["pts"]) == 3:
                text = f"{angle_deg(*m['pts']):.1f}°"
            if text:
                x, y = pts[-1]
                c.create_text(x + 8, y - 8, text=text, fill=MEASURE, anchor="sw", font=("", 12, "bold"))

    # ----------------------------------------------------- Maus
    def _inside_image(self, mx, my) -> bool:
        _ox, _oy, _s, rows, cols, ry, rx = self._geom
        return 0 <= mx < cols * rx and 0 <= my < rows * ry

    def _press(self, event):
        if self._geom is None:
            return
        self.viewer.set_active(self)
        tool = self.viewer.tool
        mx, my = self.canvas_to_mm(event.x, event.y)
        self._drag = (event.x, event.y, list(self.pan), self.zoom, tuple(self.viewer.window))
        if tool == "navigate":
            if self._inside_image(mx, my):
                self.set_cursor_from_mm(mx, my)
        elif tool == "distance":
            self.viewer.pending = {"key": self.measurement_key(), "kind": "distance", "pts": [(mx, my), (mx, my)]}
            self.schedule()
        elif tool == "angle":
            p = self.viewer.pending
            if p is None or p["key"] != self.measurement_key() or p["kind"] != "angle":
                p = self.viewer.pending = {"key": self.measurement_key(), "kind": "angle", "pts": []}
            p["pts"].append((mx, my))
            if len(p["pts"]) == 3:
                self.viewer.measurements.append(p)
                self.viewer.pending = None
            self.schedule()
        elif tool == "curve":
            if self.kind != AX:
                self.viewer.status("Die Panoramakurve wird in der axialen Ansicht (oben links) gezeichnet.")
                return
            if self._inside_image(mx, my):
                sz, sy, sx = self.viewer.data.spacing
                self.viewer.add_curve_point((mx / sx - 0.5, my / sy - 0.5))

    def _motion_drag(self, event):
        if self._geom is None or self._drag is None:
            return
        tool = self.viewer.tool
        x0, y0, pan0, zoom0, win0 = self._drag
        dx, dy = event.x - x0, event.y - y0
        mx, my = self.canvas_to_mm(event.x, event.y)
        if tool == "navigate":
            if self._inside_image(mx, my):
                self.set_cursor_from_mm(mx, my)
        elif tool == "pan":
            self.pan = [pan0[0] + dx, pan0[1] + dy]
            self.schedule()
        elif tool == "zoom":
            self.zoom = min(max(zoom0 * math.exp(-dy / 150.0), 0.3), 20.0)
            self.schedule()
        elif tool == "window":
            self.viewer.drag_window(win0, dx, dy)
        elif tool == "distance" and self.viewer.pending is not None:
            self.viewer.pending["pts"][1] = (mx, my)
            self.schedule()
        self._hover(event)

    def _release(self, _event):
        if self.viewer.tool == "distance" and self.viewer.pending is not None:
            p = self.viewer.pending
            if distance_mm(*p["pts"]) > 0.2:
                self.viewer.measurements.append(p)
            self.viewer.pending = None
            self.schedule()
        self._drag = None

    def _double(self, _event):
        if self.viewer.tool == "curve" and self.kind == AX:
            self.viewer.finish_curve()
        elif self.viewer.tool in ("navigate", "pan", "zoom", "window"):
            self.viewer.toggle_maximize(self)

    def _wl_press(self, event):
        self._wl = (event.x, event.y, tuple(self.viewer.window))

    def _wl_drag(self, event):
        x0, y0, win0 = getattr(self, "_wl", (event.x, event.y, tuple(self.viewer.window)))
        self.viewer.drag_window(win0, event.x - x0, event.y - y0)

    def _wheel(self, event):
        if self._geom is None:
            return
        self.scroll(wheel_steps(event))

    def _zoom_by(self, factor):
        self.zoom = min(max(self.zoom * factor, 0.3), 20.0)
        self.schedule()

    def _on_slider(self, value):
        if self._slider_lock or self.viewer.data is None:
            return
        target = int(round(float(value)))
        if target != self.index:
            self.set_index(target)

    def _hover(self, event):
        if self._geom is None:
            return
        mx, my = self.canvas_to_mm(event.x, event.y)
        if not self._inside_image(mx, my):
            self.viewer.status_pos("")
            return
        text = f"{TITLES[self.kind]}:  x {mx:.1f} mm   y {my:.1f} mm"
        vox = self.voxel_from_mm(mx, my)
        if vox is not None:
            text += f"   Wert {self.viewer.data.value_at(*vox):.0f}"
        self.viewer.status_pos(text)

    def reset_view(self):
        self.zoom = 1.0
        self.pan = [0.0, 0.0]
        self.schedule()


class PanoramaPanel(SlicePanel):
    """Panorama-Rekonstruktion; Mausrad verschiebt die Schicht nach innen/außen."""

    STEP_MM = 0.5

    def __init__(self, viewer, parent):
        super().__init__(viewer, parent, PAN, header=False)
        self.offset_mm = 0.0
        self._cache = None
        self._base = None

    def image(self):
        if len(self.viewer.curve_points) < 2 or not self.viewer.curve_done:
            raise ValueError("Noch keine Panoramakurve.\n\nWerkzeug „⌒ Panoramakurve“ wählen und in der "
                             "axialen Ansicht (oben links) entlang des Zahnbogens klicken. "
                             "Doppelklick beendet die Kurve.")
        key = (tuple(self.viewer.curve_points), round(self.offset_mm, 2), self.viewer.pan_thickness)
        if self._cache is None or self._cache[0] != key:
            img, spacing, base = self.viewer.data.panorama(self.viewer.curve_points, self.offset_mm,
                                                           self.viewer.pan_thickness)
            self._cache = (key, img, spacing)
            self._base = base
        return self._cache[1], self._cache[2]

    @property
    def index(self) -> int:
        return int(round(self.offset_mm / self.STEP_MM)) + 40

    @property
    def count(self) -> int:
        return 81

    def set_index(self, value: int) -> None:
        self.offset_mm = (int(min(max(value, 0), 80)) - 40) * self.STEP_MM
        self.schedule()
        self.viewer.status(f"Panoramaschicht {self.offset_mm:+.1f} mm gegenüber der Kurve")

    def position_text(self) -> str:
        return f"Schicht {self.offset_mm:+.1f} mm"

    def measurement_key(self):
        return PAN, tuple(self.viewer.curve_points), round(self.offset_mm, 2)

    def cursor_mm(self):
        sz = self.viewer.data.spacing[0]
        Z = self.viewer.data.shape[0]
        return -1e6, (Z - 1 - self.viewer.cursor[0] + 0.5) * sz

    def _draw_overlays(self, W, H):
        c = self.canvas
        if self.viewer.show_crosshair and self._geom is not None:
            _mx, my = self.cursor_mm()
            _cx, cy = self.mm_to_canvas(0, my)
            c.create_line(0, cy, W + 4, cy, fill=COLORS[AX], dash=(6, 4))
        for text, x, anchor in (("R", 8, "w"), ("L", W - 4, "e")):
            c.create_text(x, H / 2, text=text, fill=MUTED, font=("", 11, "bold"), anchor=anchor)
        c.create_text(W / 2, H - 4, text=self.position_text() + "  ·  Mausrad: Schicht nach innen/außen",
                      fill=MUTED, anchor="s", font=("", 9))
        self._draw_measurements()

    def set_cursor_from_mm(self, mx, my):
        if self._base is None:
            return
        _ox, _oy, _s, rows, cols, ry, rx = self._geom
        sz, sy, sx = self.viewer.data.spacing
        Z, Y, X = self.viewer.data.shape
        col = int(min(max(mx // rx, 0), len(self._base) - 1))
        px, py = self._base[col]
        z = Z - 1 - int(my // ry)
        self.viewer.set_cursor(min(max(z, 0), Z - 1), int(min(max(py // sy, 0), Y - 1)),
                               int(min(max(px // sx, 0), X - 1)))

    def voxel_from_mm(self, mx, my):
        if self._base is None or self._geom is None:
            return None
        ry, rx = self._geom[5], self._geom[6]
        sz, sy, sx = self.viewer.data.spacing
        Z = self.viewer.data.shape[0]
        col = int(min(max(mx // rx, 0), len(self._base) - 1))
        px, py = self._base[col]
        return Z - 1 - int(my // ry), int(py // sy), int(px // sx)


# ==================================================================== 3D-Ansicht
class Render3DPanel(tk.Frame):
    def __init__(self, viewer: "ViewerWindow", parent):
        super().__init__(parent, background=PANEL_BG)
        self.viewer = viewer
        self.kind = V3D
        self.azimuth = 0.0
        self.elevation = 0.25
        self.zoom = 1.3
        self.mode = "surface"
        self.threshold = None
        self._photo = None
        self._job = None
        self._drag = None
        self._busy = False
        self._quality = "high"

        controls = tk.Frame(self, background=PANEL_BG)
        controls.pack(fill="x", padx=4, pady=(2, 0))
        self.mode_var = tk.StringVar(value="Oberfläche (Knochen/Zähne)")
        mode = ttk.Combobox(controls, textvariable=self.mode_var, state="readonly", width=24,
                            values=("Oberfläche (Knochen/Zähne)", "Röntgen (Durchleuchtung)"))
        mode.pack(side="left")
        mode.bind("<<ComboboxSelected>>", self._mode_changed)
        tk.Label(controls, text="Schwelle", background=PANEL_BG, foreground=MUTED).pack(side="left", padx=(10, 4))
        self.thr_scale = ttk.Scale(controls, orient="horizontal", from_=0, to=1, command=self._thr_changed)
        self.thr_scale.pack(side="left", fill="x", expand=True)
        tk.Button(controls, text="Vorn", command=lambda: self.set_view(0.0, 0.0), relief="flat",
                  background=PANEL_BG, foreground=FG, activebackground="#2b3138", highlightthickness=0
                  ).pack(side="left", padx=(8, 0))
        tk.Button(controls, text="Seite", command=lambda: self.set_view(math.pi / 2, 0.0), relief="flat",
                  background=PANEL_BG, foreground=FG, activebackground="#2b3138", highlightthickness=0
                  ).pack(side="left")
        tk.Button(controls, text="Oben", command=lambda: self.set_view(0.0, math.pi / 2 - 0.01), relief="flat",
                  background=PANEL_BG, foreground=FG, activebackground="#2b3138", highlightthickness=0
                  ).pack(side="left")

        self.canvas = tk.Canvas(self, background="#0f1215", highlightthickness=2,
                                highlightbackground=PANEL_BG, width=200, height=200)
        self.canvas.pack(fill="both", expand=True)
        tk.Label(self, text="Ziehen: drehen · Mausrad: zoomen · Doppelklick: groß/klein", background=PANEL_BG,
                 foreground=MUTED, font=("", 9)).pack(pady=(2, 4))
        c = self.canvas
        c.bind("<Configure>", lambda _e: self.schedule("high"))
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._drag_move)
        c.bind("<ButtonRelease-1>", lambda _e: self.schedule("high"))
        c.bind("<Double-Button-1>", lambda _e: self.viewer.toggle_maximize(self.viewer.quad4))
        c.bind("<MouseWheel>", self._wheel)
        c.bind("<Button-4>", self._wheel)
        c.bind("<Button-5>", self._wheel)
        c.bind("<Enter>", lambda _e: self.viewer.set_active(self))

    def init_threshold(self):
        data = self.viewer.data
        self.thr_scale.configure(from_=data.lo, to=data.hi)
        self.threshold = data.lo + 0.5 * (data.hi - data.lo)
        self.thr_scale.set(self.threshold)

    def set_view(self, az, el):
        self.azimuth, self.elevation = az, el
        self.schedule("high")

    def _mode_changed(self, _e=None):
        self.mode = "mip" if self.mode_var.get().startswith("Röntgen") else "surface"
        self.schedule("high")

    def _thr_changed(self, value):
        self.threshold = float(value)
        if self.mode == "surface":
            self.schedule("low")
            self.schedule("high", delay=400)

    def _press(self, event):
        self._drag = (event.x, event.y, self.azimuth, self.elevation)
        self.viewer.set_active(self)

    def _drag_move(self, event):
        if self._drag is None:
            return
        x0, y0, az0, el0 = self._drag
        self.azimuth = az0 + (event.x - x0) * 0.012
        self.elevation = min(max(el0 + (event.y - y0) * 0.012, -1.55), 1.55)
        self.schedule("low")

    def _wheel(self, event):
        self.zoom = min(max(self.zoom * (1.12 if wheel_steps(event) > 0 else 1 / 1.12), 0.5), 6.0)
        self.schedule("low")
        self.schedule("high", delay=350)

    def schedule(self, quality="high", delay=None):
        if self.viewer.data is None or not self.winfo_ismapped():
            return
        if self._job is not None:
            self.after_cancel(self._job)
        self._quality = quality
        self._job = self.after(delay if delay is not None else (10 if quality == "low" else 120), self.render)

    def render(self):
        self._job = None
        if self.viewer.data is None or not self.winfo_exists():
            return
        W, H = max(self.canvas.winfo_width() - 4, 10), max(self.canvas.winfo_height() - 4, 10)
        side = min(W, H)
        size = min(side, 140) if self._quality == "low" else min(side, 340)
        if self.threshold is None:
            self.init_threshold()
        if self._quality == "high":
            self.viewer.config(cursor="watch")
            self.update_idletasks()
        try:
            rgb = self.viewer.data.render3d(self.azimuth, self.elevation, size, self.mode, self.threshold, self.zoom)
        finally:
            self.viewer.config(cursor="")
        if size != side:   # auf Anzeigegröße hochskalieren (nächster Nachbar)
            idx = (np.arange(side) * size // side).astype(np.int64)
            rgb = rgb[idx][:, idx]
        self._photo = tk.PhotoImage(data=to_photo_data(np.ascontiguousarray(rgb)), format="ppm")
        self.canvas.delete("all")
        self.canvas.create_image(W // 2 + 2, H // 2 + 2, image=self._photo)
        if self.mode == "surface":
            self.canvas.create_text(8, H - 4, anchor="sw", fill=MUTED, font=("", 9),
                                    text="Schwelle verschieben, bis Knochen und Zähne gut sichtbar sind")


# ===================================================================== Fenster
class ViewerWindow(tk.Toplevel):
    def __init__(self, parent, series=None, folder=None):
        super().__init__(parent)
        from .gui import screen_size

        self.series = series
        self.folder = folder
        self.data: VolumeData | None = None
        self.cursor = [0, 0, 0]
        self.window = [0.0, 1.0]
        self.slab_mm = 0.0
        self.pan_thickness = 8.0
        self.tool = "navigate"
        self.show_crosshair = True
        self.measurements: list = []
        self.pending = None
        self.curve_points: list = []
        self.curve_done = False
        self.active = None
        self.maximized = None
        self._queue: "queue.Queue" = queue.Queue()
        self._cancel = threading.Event()

        name = series.patient.display_name if series is not None else (folder.name if folder else "")
        self.title(f"Notfall-Viewer – {name}")
        self.configure(background=BG)
        sw, sh = screen_size(self)
        width, height = min(1400, sw - 40), min(940, sh - 90)
        self.geometry(f"{width}x{height}+{max(0, (sw - width) // 2)}+{max(0, (sh - height) // 3)}")
        self.minsize(min(900, width), min(620, height))
        self.protocol("WM_DELETE_WINDOW", self.close)

        self._build_loading()
        threading.Thread(target=self._load_worker, daemon=True).start()
        self.after(80, self._poll)

    # ------------------------------------------------------- Laden
    def _build_loading(self):
        self.loading = tk.Frame(self, background=BG)
        self.loading.place(relx=0.5, rely=0.45, anchor="center")
        tk.Label(self.loading, text="Aufnahme wird geladen …", background=BG, foreground=FG,
                 font=("", 16, "bold")).pack(pady=(0, 12))
        self.load_bar = ttk.Progressbar(self.loading, length=420, mode="determinate")
        self.load_bar.pack()
        self.load_text = tk.Label(self.loading, text="", background=BG, foreground=MUTED)
        self.load_text.pack(pady=(8, 0))

    def _load_worker(self):
        try:
            series = self.series
            if series is None:
                from .scanner import KIND_VOLUME, scan_source

                self._queue.put(("TEXT", "Ordner wird durchsucht …"))
                volumes = [s for s in scan_source(self.folder).series if s.kind == KIND_VOLUME]
                if not volumes:
                    raise ValueError("In diesem Ordner wurde keine DVT-Aufnahme gefunden.")
                series = volumes[0]
                self.series = series
            data = VolumeData.load(series, progress=lambda d, t: self._queue.put(("PROGRESS", (d, t))),
                                   cancelled=self._cancel.is_set)
            self._queue.put(("LOADED", data))
        except ViewerCancelled:
            pass
        except MemoryError:
            self._queue.put(("ERROR", "Für diese Aufnahme reicht der Arbeitsspeicher nicht aus."))
        except Exception as exc:  # noqa: BLE001
            self._queue.put(("ERROR", str(exc)))

    def _poll(self):
        if not self.winfo_exists():
            return
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "PROGRESS":
                    done, total = payload
                    self.load_bar.configure(maximum=total, value=done)
                    self.load_text.configure(text=f"Schicht {done} von {total}")
                elif kind == "TEXT":
                    self.load_text.configure(text=payload)
                elif kind == "LOADED":
                    self._on_loaded(payload)
                elif kind == "ERROR":
                    messagebox.showerror("Notfall-Viewer", f"Die Aufnahme kann nicht angezeigt werden.\n\n{payload}",
                                         parent=self)
                    self.close()
                    return
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def _on_loaded(self, data: VolumeData):
        self.data = data
        self.cursor = self.start_cursor()
        self.window = [(data.lo + data.hi) / 2, data.hi - data.lo]
        self.loading.destroy()
        self._build_ui()
        self.redraw_all()
        self.after(300, self.panel3d.render)

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        style = ttk.Style(self)
        style.configure("Viewer.Toolbutton", font=("", 11), padding=(10, 6))

        top = tk.Frame(self, background=BG)
        top.pack(fill="x", padx=8, pady=(8, 4))
        self.tool_var = tk.StringVar(value=self.tool)
        for key, label, _hint in TOOLS:
            ttk.Radiobutton(top, text=label, value=key, variable=self.tool_var, style="Toolbutton",
                            command=self._tool_changed).pack(side="left", padx=(0, 4))

        bar2 = tk.Frame(self, background=BG)
        bar2.pack(fill="x", padx=8, pady=(0, 6))
        tk.Label(bar2, text="Darstellung:", background=BG, foreground=MUTED).pack(side="left")
        self.preset_var = tk.StringVar(value=WINDOW_PRESETS[0])
        preset = ttk.Combobox(bar2, textvariable=self.preset_var, values=WINDOW_PRESETS, state="readonly", width=16)
        preset.pack(side="left", padx=(4, 14))
        preset.bind("<<ComboboxSelected>>", lambda _e: self.apply_preset(self.preset_var.get()))
        tk.Label(bar2, text="Schichtdicke:", background=BG, foreground=MUTED).pack(side="left")
        self.slab_var = tk.StringVar(value=SLABS[0][0])
        slab = ttk.Combobox(bar2, textvariable=self.slab_var, values=[s[0] for s in SLABS], state="readonly", width=16)
        slab.pack(side="left", padx=(4, 14))
        slab.bind("<<ComboboxSelected>>", self._slab_changed)
        self.cross_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar2, text="Fadenkreuz anzeigen", variable=self.cross_var,
                        command=self._cross_changed).pack(side="left", padx=(0, 14))
        for text, cmd in (("Hilfe", self.show_help), ("Messungen löschen", self.clear_measurements),
                          ("Ansicht zurücksetzen", self.reset_views)):
            ttk.Button(bar2, text=text, command=cmd).pack(side="right", padx=(6, 0))

        self.grid_frame = tk.Frame(self, background=BG)
        self.grid_frame.pack(fill="both", expand=True, padx=8)
        for i in range(2):
            self.grid_frame.columnconfigure(i, weight=1, uniform="col")
            self.grid_frame.rowconfigure(i, weight=1, uniform="row")
        self.panels = {AX: SlicePanel(self, self.grid_frame, AX),
                       COR: SlicePanel(self, self.grid_frame, COR),
                       SAG: SlicePanel(self, self.grid_frame, SAG)}
        self.quad4 = tk.Frame(self.grid_frame, background=PANEL_BG)
        header = tk.Frame(self.quad4, background=PANEL_BG)
        header.pack(fill="x")
        self.q4_color = tk.Frame(header, background=COLORS[V3D], width=6)
        self.q4_color.pack(side="left", fill="y")
        self.q4_var = tk.StringVar(value=V3D)
        for key in (V3D, PAN):
            ttk.Radiobutton(header, text=TITLES[key], value=key, variable=self.q4_var, style="Toolbutton",
                            command=self._q4_changed).pack(side="left", padx=(6, 0), pady=2)
        self.q4_body = tk.Frame(self.quad4, background=PANEL_BG)
        self.q4_body.pack(fill="both", expand=True)
        self.panel3d = Render3DPanel(self, self.q4_body)
        self.panel_pan = PanoramaPanel(self, self.q4_body)
        self.panel3d.pack(fill="both", expand=True)

        self._positions = {self.panels[AX]: (0, 0), self.panels[COR]: (0, 1),
                           self.panels[SAG]: (1, 0), self.quad4: (1, 1)}
        for widget, (r, c) in self._positions.items():
            widget.grid(row=r, column=c, sticky="nsew", padx=3, pady=3)

        status = tk.Frame(self, background=BG)
        status.pack(fill="x", padx=10, pady=(4, 6))
        self.status_var = tk.StringVar()
        self.pos_var = tk.StringVar()
        tk.Label(status, textvariable=self.status_var, background=BG, foreground=FG, anchor="w").pack(side="left")
        tk.Label(status, textvariable=self.pos_var, background=BG, foreground=MUTED).pack(side="right")
        info = (f"{self.data.label}  ·  {self.data.shape[2]} × {self.data.shape[1]} × {self.data.shape[0]} Voxel, "
                f"{self.data.spacing[2]:.2g} × {self.data.spacing[1]:.2g} × {self.data.spacing[0]:.2g} mm")
        if self.data.missing:
            info += f"  ·  {len(self.data.missing)} fehlende Schicht(en) schwarz"
        foot = tk.Frame(self, background=BG)
        foot.pack(fill="x", padx=10, pady=(0, 6))
        tk.Label(foot, text=info, background=BG, foreground=MUTED).pack(side="left")
        tk.Label(foot, text="Notfall-Viewer – nur zur Ansicht, kein zertifiziertes Diagnoseprogramm",
                 background=BG, foreground="#ff8a65").pack(side="right")

        for key, seq in (("<Up>", 1), ("<Down>", -1), ("<Prior>", 10), ("<Next>", -10)):
            self.bind(key, lambda _e, s=seq: self._key_scroll(s))
        self.bind("<Escape>", lambda _e: self.cancel_pending())
        self.bind("<Delete>", lambda _e: self.undo_measurement())
        self.bind("<BackSpace>", lambda _e: self.undo_measurement())
        self.set_active(self.panels[AX])
        self._tool_changed()

    def start_cursor(self) -> list:
        """Bildmitte - axial möglichst auf einer vorhandenen (nicht ergänzten) Schicht."""
        Z, Y, X = self.data.shape
        present = [z for z in range(Z) if z not in self.data.missing]
        z = min(present, key=lambda i: abs(i - Z // 2)) if present else Z // 2
        return [z, Y // 2, X // 2]

    # ------------------------------------------------- Zustand ändern
    def set_cursor(self, z, y, x):
        if [z, y, x] != self.cursor:
            self.cursor = [z, y, x]
            self.redraw_slices()

    def redraw_slices(self):
        for p in self.panels.values():
            p.schedule()
        if self.q4_var.get() == PAN:
            self.panel_pan.schedule()

    def redraw_all(self):
        self.redraw_slices()
        self.panel_pan.schedule()

    def set_active(self, panel):
        if self.active is not panel:
            old, self.active = self.active, panel
            for p in (old, panel):
                if isinstance(p, SlicePanel):
                    p.schedule()

    def status(self, text):
        self.status_var.set(text)

    def status_pos(self, text):
        self.pos_var.set(text)

    def drag_window(self, win0, dx, dy):
        span = self.data.hi - self.data.lo
        centre = win0[0] - dy * span / 400.0
        width = max(win0[1] + dx * span / 300.0, span / 200.0)
        self.window = [centre, width]
        self.preset_var.set("")
        self.redraw_all()

    def apply_preset(self, name):
        lo, hi = self.data.lo, self.data.hi
        span = hi - lo
        a, b = {"Automatisch": (0.0, 1.0), "Knochen / Zähne": (0.35, 1.0),
                "Weichgewebe": (0.12, 0.55), "Kontrastreich": (0.3, 0.8)}.get(name, (0.0, 1.0))
        self.window = [lo + span * (a + b) / 2, span * (b - a)]
        self.redraw_all()

    def _slab_changed(self, _e=None):
        self.slab_mm = dict(SLABS).get(self.slab_var.get(), 0.0)
        self.redraw_all()

    def _cross_changed(self):
        self.show_crosshair = self.cross_var.get()
        self.redraw_all()

    def _tool_changed(self):
        self.tool = self.tool_var.get()
        self.cancel_pending()
        hint = next(h for k, _l, h in TOOLS if k == self.tool)
        self.status(hint)
        if self.tool == "curve":
            self.curve_points = []
            self.curve_done = False
            self.q4_var.set(PAN)
            self._q4_changed()
            self.panels[AX].schedule()
        cursor = {"navigate": "crosshair", "pan": "fleur", "zoom": "sizing", "window": "exchange",
                  "distance": "tcross", "angle": "tcross", "curve": "pencil"}.get(self.tool, "")
        for p in list(self.panels.values()) + [self.panel_pan]:
            try:
                p.canvas.configure(cursor=cursor)
            except tk.TclError:
                p.canvas.configure(cursor="")

    def _q4_changed(self):
        which = self.q4_var.get()
        self.q4_color.configure(background=COLORS[which])
        if which == PAN:
            self.panel3d.pack_forget()
            self.panel_pan.pack(fill="both", expand=True)
            self.panel_pan.schedule()
        else:
            self.panel_pan.pack_forget()
            self.panel3d.pack(fill="both", expand=True)
            self.panel3d.schedule("high")

    def _key_scroll(self, steps):
        panel = self.active if isinstance(self.active, SlicePanel) else self.panels[AX]
        panel.scroll(steps)

    def add_curve_point(self, point):
        if self.curve_done:
            self.curve_points = []
            self.curve_done = False
        self.curve_points.append(point)
        n = len(self.curve_points)
        self.status(f"{n} Punkt(e) gesetzt. Weiter entlang des Zahnbogens klicken – Doppelklick beendet die Kurve.")
        self.panels[AX].schedule()

    def finish_curve(self):
        # Ein Doppelklick erzeugt vorher zwei Einzelklicks auf dieselbe Stelle -> Duplikate entfernen
        cleaned = []
        for p in self.curve_points:
            if not cleaned or math.hypot(p[0] - cleaned[-1][0], p[1] - cleaned[-1][1]) > 2:
                cleaned.append(p)
        self.curve_points = cleaned
        if len(cleaned) < 2:
            self.status("Bitte mindestens zwei Punkte entlang des Zahnbogens setzen.")
            return
        self.curve_done = True
        self.panel_pan.offset_mm = 0.0
        self.q4_var.set(PAN)
        self._q4_changed()
        self.tool_var.set("navigate")
        self._tool_changed()
        self.status("Panorama erstellt. Mausrad im Panorama: Schicht nach innen/außen verschieben.")
        self.panels[AX].schedule()

    def cancel_pending(self):
        if self.pending is not None:
            self.pending = None
            self.redraw_all()

    def undo_measurement(self):
        if self.measurements:
            self.measurements.pop()
            self.redraw_all()

    def clear_measurements(self):
        self.measurements.clear()
        self.pending = None
        self.redraw_all()

    def reset_views(self):
        for p in list(self.panels.values()) + [self.panel_pan]:
            p.reset_view()
        self.cursor = self.start_cursor()
        self.preset_var.set(WINDOW_PRESETS[0])
        self.apply_preset(WINDOW_PRESETS[0])
        self.panel3d.zoom = 1.3
        self.panel3d.set_view(0.0, 0.25)
        if self.maximized is not None:
            self.toggle_maximize(self.maximized)

    def toggle_maximize(self, panel):
        if isinstance(panel, PanoramaPanel):
            panel = self.quad4
        if self.maximized is None:
            for widget in self._positions:
                if widget is not panel:
                    widget.grid_remove()
            panel.grid(row=0, column=0, rowspan=2, columnspan=2, sticky="nsew", padx=3, pady=3)
            self.maximized = panel
        else:
            for widget, (r, c) in self._positions.items():
                widget.grid(row=r, column=c, rowspan=1, columnspan=1, sticky="nsew", padx=3, pady=3)
            self.maximized = None
        self.after(50, self.redraw_all)
        self.after(80, lambda: self.panel3d.schedule("high"))

    def show_help(self):
        lines = ["So bedienen Sie den Notfall-Viewer:", ""]
        lines += [f"{label.split('  ', 1)[-1]}:  {hint}" for _k, label, hint in TOOLS]
        lines += ["", "Immer möglich:",
                  "• Mausrad über einer Ansicht: durch die Schichten blättern",
                  "• Pfeiltasten ↑/↓ (Bild ↑/↓ = 10 Schichten): blättern in der zuletzt benutzten Ansicht",
                  "• Rechte Maustaste ziehen (Mac: Ctrl + Klick ziehen): Helligkeit/Kontrast",
                  "• Strg + Mausrad: zoomen",
                  "• Doppelklick: Ansicht groß/klein",
                  "• Entf: letzte Messung löschen, Esc: angefangene Messung abbrechen",
                  "",
                  "Messungen gelten für die jeweilige Schicht. Bei unbekannter Voxelgröße sind sie ungenau.",
                  "Dies ist ein Notbehelf und kein zertifiziertes Diagnoseprogramm."]
        messagebox.showinfo("Hilfe – Notfall-Viewer", "\n".join(lines), parent=self)

    def close(self):
        self._cancel.set()
        self.destroy()


def open_viewer(parent, series=None, folder=None) -> ViewerWindow:
    win = ViewerWindow(parent, series=series, folder=folder)
    win.lift()
    win.focus_set()
    return win
