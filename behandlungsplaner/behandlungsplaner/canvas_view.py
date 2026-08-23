"""Interaktive Tkinter-Canvas: zeigt das OPG, die Befund-Symbole und (optional)
das FDI-Kalibrierraster; verarbeitet Zoom/Pan, Drag&Drop aus der Palette,
Verschieben/Skalieren/Rotieren sowie das Editieren einzelner Positionen.
"""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import simpledialog
from typing import Optional

from PIL import Image, ImageTk

from . import shapes, snapping, theme
from .fdi import (
    ALL_FDI_TEETH,
    LOWER_ROW_LEFT_TO_RIGHT,
    UPPER_ROW_LEFT_TO_RIGHT,
    default_calibration_layout,
    teeth_between,
)
from .models import KIND_ANCHOR_TYPE, KIND_BRUECKE, KIND_LABELS, PlanItem

HANDLE_SIZE = 9
ROTATE_HANDLE_LOCAL_Y = -0.78
MIN_SIZE_FRACTION = 0.006
DEFAULT_NEW_WIDTH_FRACTION = 0.045
# Ab dieser Kantenlaenge gilt das Canvas-Widget als tatsaechlich ausgelegt.
MIN_USABLE_CANVAS_PX = 40

CALIB_POINT_RADIUS = 6
CALIB_COLOR = "#00c2b2"
CALIB_COLOR_IDLE = "#5f9c96"
CALIB_FILL_ACTIVE = "#d6f7f3"
SELECTION_COLOR = "#2f7ef4"
SNAP_COLOR = "#12b886"
HANDLE_FILL = "#ffffff"


def _try_resample():
    try:
        return Image.Resampling.LANCZOS
    except AttributeError:  # Pillow < 9.1
        return Image.LANCZOS


_RESAMPLE = _try_resample()


class PlanCanvas(tk.Canvas):
    def __init__(self, parent, **kwargs):
        kwargs.setdefault("bg", theme.BG_CANVAS)
        kwargs.setdefault("highlightthickness", 0)
        super().__init__(parent, **kwargs)

        self.plan = None
        self.pil_image = None
        self.image_w = 0
        self.image_h = 0

        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0

        self.selected_item_id: Optional[str] = None

        self.on_change = None            # callable()
        self.on_selection_change = None  # callable(item_id_or_None)

        self._photo = None
        self._photo_zoom = None
        self._needs_fit = False

        self._drag = None
        self._external_drag_kind = None
        # FDI-Nummer des Zahns, auf den gerade eingerastet wird - treibt die
        # Hervorhebung waehrend Drag&Drop bzw. Verschieben.
        self._snap_target_tooth = None
        # Per Klick in der Palette vorgemerkte Befundart: der naechste Klick
        # ins Bild setzt sie (Alternative zum Ziehen).
        self._armed_kind = None
        self.on_armed_consumed = None
        # Solange aktiv, werden ausschliesslich die Rasterpunkte bearbeitet.
        # Ohne diesen Modus waeren Rasterpunkte unter einem eingerasteten
        # Symbol nicht mehr greifbar.
        self.calibration_edit_mode = False

        self.bind("<Configure>", self._on_configure)
        self.bind("<Motion>", self._on_hover_motion)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_motion)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<ButtonPress-3>", self._on_button3_press)
        self.bind("<B3-Motion>", self._on_pan_motion)
        self.bind("<MouseWheel>", self._on_wheel)
        self.bind("<Button-4>", lambda e: self._zoom_step(1.15, e))
        self.bind("<Button-5>", lambda e: self._zoom_step(1 / 1.15, e))

    # ------------------------------------------------------------- Laden
    def load(self, plan, pil_image: Image.Image):
        self.plan = plan
        self.pil_image = pil_image
        self.image_w, self.image_h = pil_image.size
        self.selected_item_id = None
        self._photo_zoom = None
        self._needs_fit = True
        self.after_idle(self.zoom_fit)

    def _notify_change(self):
        if self.on_change:
            self.on_change()

    def _notify_selection(self):
        if self.on_selection_change:
            self.on_selection_change(self.selected_item_id)

    # --------------------------------------------------------------- View
    def _canvas_size(self):
        return self.winfo_width(), self.winfo_height()

    def _has_usable_size(self):
        """True, sobald das Widget tatsaechlich ausgelegt ist. Vor dem ersten
        Layout meldet Tk 1x1 - ein Einpassen darauf ergaebe einen
        Mikro-Zoom, bei dem vom Roentgenbild nichts mehr zu sehen waere."""
        cw, ch = self._canvas_size()
        return cw >= MIN_USABLE_CANVAS_PX and ch >= MIN_USABLE_CANVAS_PX

    def _on_configure(self, _event):
        # Nach dem Laden so lange erneut einpassen, bis das Widget eine
        # brauchbare Groesse hat (Layout laeuft asynchron, insbesondere in
        # PanedWindows).
        if self.plan is not None and self._needs_fit:
            self.zoom_fit()
        else:
            self._redraw()

    def zoom_fit(self):
        if not self.pil_image:
            return
        if not self._has_usable_size():
            # Noch nicht ausgelegt: Einpassen aufheben, bis <Configure> mit
            # echten Massen kommt.
            self._needs_fit = True
            return
        cw, ch = self._canvas_size()
        self.zoom = min(cw / self.image_w, ch / self.image_h) * 0.96
        self.pan_x = (cw - self.image_w * self.zoom) / 2
        self.pan_y = (ch - self.image_h * self.zoom) / 2
        self._needs_fit = False
        self._redraw()

    def zoom_100(self):
        cw, ch = self.winfo_width(), self.winfo_height()
        self._set_zoom(1.0, center_canvas=(cw / 2, ch / 2))

    def _set_zoom(self, new_zoom, center_canvas):
        new_zoom = max(0.05, min(new_zoom, 8.0))
        cx, cy = center_canvas
        img_x, img_y = self.canvas_to_img(cx, cy)
        self.zoom = new_zoom
        self.pan_x = cx - img_x * self.zoom
        self.pan_y = cy - img_y * self.zoom
        self._redraw()

    def _zoom_step(self, factor, event):
        if not self.pil_image:
            return
        self._set_zoom(self.zoom * factor, (event.x, event.y))

    def _on_wheel(self, event):
        factor = 1.15 if event.delta > 0 else 1 / 1.15
        self._zoom_step(factor, event)

    def _on_button3_press(self, event):
        self._drag = {"mode": "pan", "start": (event.x, event.y),
                      "pan0": (self.pan_x, self.pan_y)}

    def _on_pan_motion(self, event):
        if not self._drag or self._drag.get("mode") != "pan":
            return
        sx, sy = self._drag["start"]
        px0, py0 = self._drag["pan0"]
        self.pan_x = px0 + (event.x - sx)
        self.pan_y = py0 + (event.y - sy)
        self._redraw()

    # ------------------------------------------------------- Koordinaten
    def img_to_canvas(self, x, y):
        return x * self.zoom + self.pan_x, y * self.zoom + self.pan_y

    def canvas_to_img(self, x, y):
        return (x - self.pan_x) / self.zoom, (y - self.pan_y) / self.zoom

    def _frac_to_canvas(self, fx, fy):
        return self.img_to_canvas(fx * self.image_w, fy * self.image_h)

    def _canvas_to_frac(self, x, y):
        ix, iy = self.canvas_to_img(x, y)
        return ix / self.image_w, iy / self.image_h

    # -------------------------------------------------------------- Draw
    def _redraw(self):
        self.delete("all")
        if self.pil_image is None:
            return
        self._draw_background()
        if self.plan.calibration_enabled:
            self._draw_calibration()
        if self._snap_target_tooth is not None:
            self._draw_snap_target(self._snap_target_tooth)
        for item in self.plan.items:
            self._draw_item(item)
        if self.selected_item_id:
            item = self.plan.get_item(self.selected_item_id)
            if item:
                self._draw_handles(item)

    def _draw_snap_target(self, tooth):
        """Hebt den Zahn hervor, auf den gerade eingerastet wird - damit
        sichtbar ist, welche Zahnnummer das Symbol bekommt."""
        if not self.plan or tooth not in self.plan.calibration_points:
            return
        fx, fy = self.plan.calibration_points[tooth]
        cx, cy = self._frac_to_canvas(fx, fy)
        spacing_px = snapping.local_spacing_px(
            self.plan.calibration_points, tooth, self.image_w, self.image_h)
        r = max(14.0, spacing_px * 0.62 * self.zoom)
        self.create_oval(cx - r, cy - r, cx + r, cy + r,
                          outline=SNAP_COLOR, width=2.5, tags=("snaptarget",))
        label_y = cy - r - 12
        self.create_text(cx, label_y, text=f"Zahn {tooth}", fill=SNAP_COLOR,
                          font=(theme.Fonts.family, 11, "bold"), tags=("snaptarget",))

    def _draw_background(self):
        if self._photo_zoom != round(self.zoom, 4):
            w = max(1, int(self.image_w * self.zoom))
            h = max(1, int(self.image_h * self.zoom))
            resized = self.pil_image.resize((w, h), _RESAMPLE)
            self._photo = ImageTk.PhotoImage(resized)
            self._photo_zoom = round(self.zoom, 4)
        x0, y0 = self.img_to_canvas(0, 0)
        self.create_image(x0, y0, image=self._photo, anchor="nw", tags=("background",))

    def _canvas_points(self, pts):
        out = []
        for x, y in pts:
            cx, cy = self.img_to_canvas(x, y)
            out.extend((cx, cy))
        return out

    def _draw_item(self, item: PlanItem):
        ops = shapes.build_draw_ops(item, self.image_w, self.image_h)
        tags = ("item", f"item:{item.id}")
        for op in ops:
            pts = self._canvas_points(op.points)
            if op.kind == "polygon":
                self.create_polygon(
                    pts, fill=op.fill or "", outline=op.outline or "",
                    width=max(1.0, op.width * self.zoom * 0.9),
                    dash=op.dash, stipple="gray50" if op.fill else "",
                    tags=tags,
                )
            elif op.kind == "line":
                self.create_line(pts, fill=op.outline, width=max(1.0, op.width * self.zoom * 0.9),
                                  dash=op.dash, tags=tags)
            elif op.kind == "text":
                size = max(7, int(op.font_size * self.zoom))
                self.create_text(pts[0], pts[1], text=op.text, font=("Helvetica", size),
                                  fill="#000000", tags=tags)
        if item.status == "durchgefuehrt":
            x0, y0, x1, y1 = shapes.bounding_box(item, self.image_w, self.image_h)
            bx, by = self.img_to_canvas(x1, y0)  # obere rechte Ecke der Bounding-Box
            r = 8
            self.create_oval(bx - r, by - r, bx + r, by + r, fill=theme.SUCCESS,
                              outline="#ffffff", width=1.5, tags=tags)
            self.create_text(bx, by, text="✓", fill="#ffffff",
                              font=(theme.Fonts.family, 9, "bold"), tags=tags)

    def _draw_calibration(self):
        # Zahnbogen als feine Verbindungslinie - macht auf einen Blick
        # sichtbar, ob das Raster sauber auf der Zahnreihe liegt.
        for row in (UPPER_ROW_LEFT_TO_RIGHT, LOWER_ROW_LEFT_TO_RIGHT):
            path = []
            for tooth in row:
                if tooth in self.plan.calibration_points:
                    path.extend(self._frac_to_canvas(*self.plan.calibration_points[tooth]))
            if len(path) >= 4:
                self.create_line(path,
                                  fill=CALIB_COLOR if self.calibration_edit_mode
                                       else CALIB_COLOR_IDLE,
                                  width=1.0, dash=(2, 4), tags=("calib",))

        # Im Bearbeitungsmodus sind die Punkte das aktive Bedienelement und
        # entsprechend kraeftig. Sonst bleiben sie bewusst zurueckhaltend -
        # sie liegen genau dort, wo auch die Symbole sitzen, und wuerden die
        # eigentliche Planung sonst optisch zudecken.
        editing = self.calibration_edit_mode
        r = CALIB_POINT_RADIUS + 3 if editing else CALIB_POINT_RADIUS - 2
        for tooth, (fx, fy) in self.plan.calibration_points.items():
            cx, cy = self._frac_to_canvas(fx, fy)
            self.create_oval(cx - r, cy - r, cx + r, cy + r,
                              outline=CALIB_COLOR if editing else CALIB_COLOR_IDLE,
                              width=3 if editing else 1.5,
                              fill=CALIB_FILL_ACTIVE if editing else "",
                              tags=("calib", f"calib:{tooth}"))
            self.create_text(cx, cy - r - 8, text=str(tooth),
                              fill=CALIB_COLOR if editing else CALIB_COLOR_IDLE,
                              font=(theme.Fonts.family, 9, "bold") if editing
                                   else (theme.Fonts.family, 8),
                              tags=("calib",))

    def _handle_positions(self, item: PlanItem) -> dict:
        """Bildpixel-Positionen aller Greifpunkte des Items."""
        if item.kind == KIND_BRUECKE:
            start = (item.x * self.image_w, item.y * self.image_h)
            end_x = item.end_x if item.end_x is not None else item.x
            end_y = item.end_y if item.end_y is not None else item.y
            end = (end_x * self.image_w, end_y * self.image_h)
            mid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
            return {"bridge_start": start, "bridge_end": end, "bridge_mid": mid}

        corners_local = [(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)]
        corners = shapes.transform_local_points(corners_local, item, self.image_w, self.image_h)
        rotate = shapes.transform_local_points([(0.0, ROTATE_HANDLE_LOCAL_Y)], item, self.image_w, self.image_h)[0]
        result = {f"corner:{i}": pt for i, pt in enumerate(corners)}
        result["rotate"] = rotate
        return result

    def _draw_handles(self, item: PlanItem):
        x0, y0, x1, y1 = shapes.bounding_box(item, self.image_w, self.image_h)
        cx0, cy0 = self.img_to_canvas(x0, y0)
        cx1, cy1 = self.img_to_canvas(x1, y1)
        self.create_rectangle(cx0, cy0, cx1, cy1, outline=SELECTION_COLOR, width=1.5,
                               dash=(4, 2), tags=("handles",))

        handle_positions = self._handle_positions(item)
        if "rotate" in handle_positions:
            rx, ry = self.img_to_canvas(*handle_positions["rotate"])
            ccx, ccy = self.img_to_canvas(item.x * self.image_w, item.y * self.image_h)
            self.create_line(ccx, ccy, rx, ry, fill=SELECTION_COLOR, width=1.5,
                              dash=(2, 2), tags=("handles",))

        for name, (px, py) in handle_positions.items():
            hx, hy = self.img_to_canvas(px, py)
            s = HANDLE_SIZE / 2
            shape = "oval" if name in ("rotate", "bridge_mid") else "rect"
            fill = HANDLE_FILL
            if shape == "oval":
                self.create_oval(hx - s, hy - s, hx + s, hy + s, outline=SELECTION_COLOR,
                                  width=1.5, fill=fill, tags=("handles", f"handle:{name}"))
            else:
                self.create_rectangle(hx - s, hy - s, hx + s, hy + s, outline=SELECTION_COLOR,
                                       width=1.5, fill=fill, tags=("handles", f"handle:{name}"))

    # ---------------------------------------------------------- Hit-Tests
    def _hit_test_handle(self, cx, cy):
        if not self.selected_item_id:
            return None
        item = self.plan.get_item(self.selected_item_id)
        if not item:
            return None
        for name, (px, py) in self._handle_positions(item).items():
            hx, hy = self.img_to_canvas(px, py)
            if abs(hx - cx) <= HANDLE_SIZE and abs(hy - cy) <= HANDLE_SIZE:
                return name
        return None

    def _hit_test_calibration(self, cx, cy):
        if not self.plan or not self.plan.calibration_enabled:
            return None
        for tooth, (fx, fy) in self.plan.calibration_points.items():
            px, py = self._frac_to_canvas(fx, fy)
            if (px - cx) ** 2 + (py - cy) ** 2 <= (CALIB_POINT_RADIUS + 4) ** 2:
                return tooth
        return None

    def _hit_test_item(self, cx, cy):
        ix, iy = self.canvas_to_img(cx, cy)
        for item in reversed(self.plan.items):
            x0, y0, x1, y1 = shapes.bounding_box(item, self.image_w, self.image_h)
            pad = 4 / self.zoom
            if x0 - pad <= ix <= x1 + pad and y0 - pad <= iy <= y1 + pad:
                return item.id
        return None

    def _nearest_calibration_point(self, fx, fy, factor=snapping.ASSIGN_FACTOR):
        """Naechster kalibrierter Zahn zu einer Bildposition (Anteilswerte)."""
        if not self.plan or not self.plan.calibration_enabled:
            return None
        return snapping.nearest_tooth(
            self.plan.calibration_points, fx, fy, self.image_w, self.image_h, factor=factor,
        )

    def _snap(self, fx, fy):
        """(x, y, zahn): magnetische Positionseinrastung plus (grosszuegigere)
        Zahnzuordnung. Ohne aktive Kalibrierung bleibt alles unveraendert."""
        if not self.plan or not self.plan.calibration_enabled:
            return fx, fy, None
        return snapping.snap_position(
            self.plan.calibration_points, fx, fy, self.image_w, self.image_h,
        )

    def _apply_tooth_to_item(self, item, tooth):
        """Weist einem Symbol einen Zahn zu und passt - solange die Groesse
        noch automatisch bestimmt wird - Breite/Hoehe an diesen Zahn an."""
        if item.fdi_tooth == tooth:
            return
        item.fdi_tooth = tooth
        if item.auto_sized:
            item.width, item.height = snapping.fit_box_for_tooth(
                item.kind, tooth, self.plan.calibration_points, self.image_w, self.image_h,
                fallback_width_fraction=item.width,
            )

    # -------------------------------------------------- Klick-zum-Setzen
    def set_armed_kind(self, kind):
        """Merkt eine Befundart vor; der naechste Klick ins Bild setzt sie."""
        self._armed_kind = kind
        self.configure(cursor="crosshair" if kind else "")
        if kind is None:
            self.delete("dragpreview")
            if self._snap_target_tooth is not None:
                self._snap_target_tooth = None
                self._redraw()

    def _on_hover_motion(self, event):
        """Vorschau auch ohne gedrueckte Maustaste, solange eine Befundart
        vorgemerkt ist - so ist vor dem Klick sichtbar, was entstehen wird."""
        if not self._armed_kind or self._drag or not self.plan:
            return
        self._external_drag_kind = self._armed_kind
        try:
            self.update_external_drag(event.x, event.y)
        finally:
            self._external_drag_kind = None

    def _on_leave(self, _event):
        if self._armed_kind:
            self.delete("dragpreview")

    # ------------------------------------------------------ Maus: Auswahl
    def _on_press(self, event):
        if self._external_drag_kind:
            return  # wird ueber begin/update/end_external_drag gesteuert

        if self._armed_kind:
            kind = self._armed_kind
            self.set_armed_kind(None)
            if self.on_armed_consumed:
                self.on_armed_consumed()
            self._place_new_item(kind, event.x, event.y)
            return

        # Im Kalibriermodus zaehlen ausschliesslich die Rasterpunkte - so
        # laesst sich das Raster auch dann noch korrigieren, wenn bereits
        # Symbole darauf liegen.
        if self.calibration_edit_mode:
            calib_tooth = self._hit_test_calibration(event.x, event.y)
            if calib_tooth is not None:
                self._drag = {"mode": "calib", "tooth": calib_tooth}
            return

        handle = self._hit_test_handle(event.x, event.y)
        if handle:
            self._start_handle_drag(handle, event)
            return

        item_id = self._hit_test_item(event.x, event.y)
        if item_id:
            self.select_item(item_id)
            item = self.plan.get_item(item_id)
            fx0, fy0 = self._canvas_to_frac(event.x, event.y)
            self._drag = {"mode": "move", "item_id": item_id,
                          "start_frac": (fx0, fy0),
                          "orig": (item.x, item.y),
                          "orig_end": (item.end_x, item.end_y)}
            return

        self.select_item(None)

    def _start_handle_drag(self, handle, event):
        item = self.plan.get_item(self.selected_item_id)
        if handle.startswith("corner:"):
            idx = int(handle.split(":")[1])
            self._drag = {"mode": "resize", "item_id": item.id, "corner": idx,
                          "orig": item.to_dict()}
        elif handle == "rotate":
            self._drag = {"mode": "rotate", "item_id": item.id}
        elif handle == "bridge_start":
            self._drag = {"mode": "bridge_start", "item_id": item.id}
        elif handle == "bridge_end":
            self._drag = {"mode": "bridge_end", "item_id": item.id}
        elif handle == "bridge_mid":
            self._drag = {"mode": "bridge_thickness", "item_id": item.id,
                          "orig_height": item.height}

    def select_item(self, item_id: Optional[str]):
        self.selected_item_id = item_id
        self._redraw()
        self._notify_selection()

    def delete_selected(self):
        if not self.selected_item_id or not self.plan:
            return
        self.plan.remove_item(self.selected_item_id)
        self.selected_item_id = None
        self._redraw()
        self._notify_selection()
        self._notify_change()

    # ------------------------------------------------------- Maus: Motion
    def _on_motion(self, event):
        if not self._drag:
            return
        mode = self._drag["mode"]
        if mode == "move":
            self._do_move(event)
        elif mode == "resize":
            self._do_resize(event)
        elif mode == "rotate":
            self._do_rotate(event)
        elif mode == "calib":
            self._do_calib_drag(event)
        elif mode in ("bridge_start", "bridge_end"):
            self._do_bridge_endpoint_drag(event, mode)
        elif mode == "bridge_thickness":
            self._do_bridge_thickness_drag(event)
        self._redraw()

    def _do_move(self, event):
        item = self.plan.get_item(self._drag["item_id"])
        fx, fy = self._canvas_to_frac(event.x, event.y)
        fx0, fy0 = self._drag["start_frac"]
        dx, dy = fx - fx0, fy - fy0
        ox, oy = self._drag["orig"]
        new_x, new_y = ox + dx, oy + dy

        if item.kind == KIND_BRUECKE:
            item.x, item.y = new_x, new_y
            if self._drag["orig_end"][0] is not None:
                oex, oey = self._drag["orig_end"]
                item.end_x, item.end_y = oex + dx, oey + dy
            item.touch()
            return

        # Zahngebundene Symbole folgen beim Verschieben der Kalibrierung: die
        # Zahnnummer (und damit Kontur und ggf. Groesse) wird laufend
        # aktualisiert, nicht nur einmalig beim Ablegen.
        if KIND_ANCHOR_TYPE.get(item.kind) == "tooth":
            new_x, new_y, tooth = self._snap(new_x, new_y)
            if tooth is not None:
                self._apply_tooth_to_item(item, tooth)
            self._snap_target_tooth = tooth
        item.x, item.y = new_x, new_y
        item.touch()

    def _do_resize(self, event):
        item = self.plan.get_item(self._drag["item_id"])
        corner = self._drag["corner"]
        su = 1.0 if corner in (1, 2) else -1.0
        sv = 1.0 if corner in (2, 3) else -1.0
        orig = self._drag["orig"]
        theta = math.radians(orig["rotation"])
        ux, uy = math.cos(theta), math.sin(theta)
        vx, vy = -math.sin(theta), math.cos(theta)

        cx0 = orig["x"] * self.image_w
        cy0 = orig["y"] * self.image_h
        w0 = orig["width"] * self.image_w
        h0 = orig["height"] * self.image_h

        opp_x = cx0 - su * (w0 / 2) * ux - sv * (h0 / 2) * vx
        opp_y = cy0 - su * (w0 / 2) * uy - sv * (h0 / 2) * vy

        mx, my = self.canvas_to_img(event.x, event.y)
        dxp, dyp = mx - opp_x, my - opp_y

        new_w = (dxp * ux + dyp * uy) * su
        new_h = (dxp * vx + dyp * vy) * sv
        min_px_w = MIN_SIZE_FRACTION * self.image_w
        min_px_h = MIN_SIZE_FRACTION * self.image_h
        new_w = max(new_w, min_px_w)
        new_h = max(new_h, min_px_h)

        new_cx = opp_x + su * (new_w / 2) * ux + sv * (new_h / 2) * vx
        new_cy = opp_y + su * (new_w / 2) * uy + sv * (new_h / 2) * vy

        item.width = new_w / self.image_w
        item.height = new_h / self.image_h
        item.x = new_cx / self.image_w
        item.y = new_cy / self.image_h
        # Ab jetzt bestimmt die Nutzerin/der Nutzer die Groesse - ein spaeteres
        # Verschieben auf einen anderen Zahn darf sie nicht mehr ueberschreiben.
        item.auto_sized = False
        item.touch()

    def _do_rotate(self, event):
        item = self.plan.get_item(self._drag["item_id"])
        cx = item.x * self.image_w
        cy = item.y * self.image_h
        mx, my = self.canvas_to_img(event.x, event.y)
        angle = math.degrees(math.atan2(my - cy, mx - cx)) + 90.0
        item.rotation = angle % 360.0
        item.touch()

    def _do_calib_drag(self, event):
        tooth = self._drag["tooth"]
        fx, fy = self._canvas_to_frac(event.x, event.y)
        fx = min(max(fx, 0.0), 1.0)
        fy = min(max(fy, 0.0), 1.0)
        self.plan.calibration_points[tooth] = (fx, fy)

    def _do_bridge_endpoint_drag(self, event, mode):
        item = self.plan.get_item(self._drag["item_id"])
        fx, fy = self._canvas_to_frac(event.x, event.y)
        fx, fy, snapped = self._snap(fx, fy)

        if mode == "bridge_start":
            item.x, item.y = fx, fy
        else:
            item.end_x, item.end_y = fx, fy
        self._snap_target_tooth = snapped

        # Pfeiler/Zwischenglieder aus beiden Endpunkten ableiten. Fuer den
        # jeweils NICHT gezogenen Endpunkt wird ohne Abstandsgrenze gesucht,
        # damit die Spanne auch dann bestimmbar bleibt, wenn dieser Endpunkt
        # etwas neben seinem Zahn liegt.
        if self.plan.calibration_enabled:
            unlimited = float("inf")
            start_tooth = snapped if mode == "bridge_start" else \
                self._nearest_calibration_point(item.x, item.y, factor=unlimited)
            end_tooth = snapped if mode == "bridge_end" else \
                self._nearest_calibration_point(item.end_x or 0.0, item.end_y or 0.0, factor=unlimited)
            if start_tooth is not None and end_tooth is not None:
                item.bridge_teeth = teeth_between(start_tooth, end_tooth)
        item.touch()

    def _do_bridge_thickness_drag(self, event):
        item = self.plan.get_item(self._drag["item_id"])
        x0, y0 = item.x * self.image_w, item.y * self.image_h
        x1 = (item.end_x if item.end_x is not None else item.x) * self.image_w
        y1 = (item.end_y if item.end_y is not None else item.y) * self.image_h
        length = math.hypot(x1 - x0, y1 - y0) or 1.0
        nx, ny = -(y1 - y0) / length, (x1 - x0) / length
        mx, my = self.canvas_to_img(event.x, event.y)
        midx, midy = (x0 + x1) / 2, (y0 + y1) / 2
        dist = abs((mx - midx) * nx + (my - midy) * ny)
        new_h = max(dist * 2, MIN_SIZE_FRACTION * self.image_h)
        item.height = new_h / self.image_h
        item.touch()

    def _on_release(self, _event):
        if self._drag and self._drag["mode"] != "pan":
            self._notify_change()
        self._drag = None
        if self._snap_target_tooth is not None:
            self._snap_target_tooth = None
            self._redraw()

    # --------------------------------------------------- Palette-Drag-API
    def begin_external_drag(self, kind: str):
        self._external_drag_kind = kind

    def update_external_drag(self, canvas_x: int, canvas_y: int):
        """Zeichnet die Vorschau des Symbols an der Mausposition - in genau der
        Kontur und Groesse, die beim Loslassen entstehen wuerde."""
        kind = self._external_drag_kind
        if not kind or not self.plan:
            return

        inside = 0 <= canvas_x <= self.winfo_width() and 0 <= canvas_y <= self.winfo_height()
        width, height, tooth = self.preview_box_for(kind, canvas_x, canvas_y)

        if tooth != self._snap_target_tooth:
            self._snap_target_tooth = tooth if inside else None
            self._redraw()
        self.delete("dragpreview")

        if not inside:
            return

        fx, fy = self._canvas_to_frac(canvas_x, canvas_y)
        if KIND_ANCHOR_TYPE.get(kind) == "tooth":
            fx, fy, _tooth = self._snap(fx, fy)

        ghost = PlanItem(kind=kind, x=fx, y=fy, width=width, height=height, fdi_tooth=tooth)
        if kind == KIND_BRUECKE:
            ghost.end_x, ghost.end_y = min(fx + 0.08, 1.0), fy
            ghost.height = 0.018

        for op in shapes.build_draw_ops(ghost, self.image_w, self.image_h):
            pts = self._canvas_points(op.points)
            if op.kind == "polygon":
                self.create_polygon(pts, fill="", outline=op.outline or SELECTION_COLOR,
                                     width=2.0, dash=(4, 3), tags=("dragpreview",))
            elif op.kind == "line":
                self.create_line(pts, fill=op.outline or SELECTION_COLOR, width=2.0,
                                  dash=(4, 3), tags=("dragpreview",))

    def end_external_drag(self, canvas_x: Optional[int], canvas_y: Optional[int]):
        kind = self._external_drag_kind
        self._external_drag_kind = None
        self.delete("dragpreview")
        self._snap_target_tooth = None
        self._redraw()
        if kind is None or canvas_x is None or not self.plan:
            return
        if not (0 <= canvas_x <= self.winfo_width() and 0 <= canvas_y <= self.winfo_height()):
            return
        self._place_new_item(kind, canvas_x, canvas_y)

    def preview_box_for(self, kind, canvas_x, canvas_y):
        """(breite, hoehe, zahn_oder_None) fuer die Drag-Vorschau an einer
        Canvasposition - identisch zu dem, was `_place_new_item` erzeugen
        wuerde. So zeigt der Ghost exakt das spaetere Ergebnis."""
        fx, fy = self._canvas_to_frac(canvas_x, canvas_y)
        tooth = None
        if KIND_ANCHOR_TYPE.get(kind) == "tooth":
            _sx, _sy, tooth = self._snap(fx, fy)
        width, height = snapping.fit_box_for_tooth(
            kind, tooth, self.plan.calibration_points if self.plan else {},
            self.image_w, self.image_h,
            fallback_width_fraction=DEFAULT_NEW_WIDTH_FRACTION,
        )
        return width, height, tooth

    def _place_new_item(self, kind, canvas_x, canvas_y):
        fx, fy = self._canvas_to_frac(canvas_x, canvas_y)

        if kind == KIND_BRUECKE:
            width, _height = snapping.fit_box_for_tooth(
                kind, None, {}, self.image_w, self.image_h,
                fallback_width_fraction=DEFAULT_NEW_WIDTH_FRACTION,
            )
            item = PlanItem(kind=kind, x=fx, y=fy, width=width, height=0.018,
                            end_x=min(fx + 0.08, 1.0), end_y=fy,
                            cost=self.plan.default_cost_for(kind))
            self.plan.add_item(item)
            self.select_item(item.id)
            self._notify_change()
            return

        fdi_tooth = None
        if KIND_ANCHOR_TYPE.get(kind, "region") == "tooth":
            fx, fy, fdi_tooth = self._snap(fx, fy)

        width, height = snapping.fit_box_for_tooth(
            kind, fdi_tooth, self.plan.calibration_points, self.image_w, self.image_h,
            fallback_width_fraction=DEFAULT_NEW_WIDTH_FRACTION,
        )

        # Die Ausrichtung zum Gegenkiefer steckt in der Symbolgeometrie
        # (shapes.arch_flip). `rotation` bleibt damit ausschliesslich fuer
        # bewusste Nutzeranpassungen an gekippten Zaehnen reserviert.
        item = PlanItem(
            kind=kind, x=fx, y=fy, width=width, height=height,
            fdi_tooth=fdi_tooth, cost=self.plan.default_cost_for(kind),
        )
        self.plan.add_item(item)
        self.select_item(item.id)
        self._notify_change()

    # --------------------------------------------------------- Kalibrierung
    def set_calibration_enabled(self, enabled: bool):
        if not self.plan:
            return
        if enabled and not self.plan.calibration_points:
            self.plan.calibration_points = default_calibration_layout()
        self.plan.calibration_enabled = enabled
        self.plan.touch()
        self._redraw()
        self._notify_change()

    def set_calibration_edit_mode(self, enabled: bool):
        """Kalibriermodus: Rasterpunkte verschieben statt Symbole bearbeiten."""
        self.calibration_edit_mode = bool(enabled)
        if enabled:
            self.select_item(None)
            self.configure(cursor="fleur")
        else:
            self.configure(cursor="")
        self._redraw()

    def reset_calibration_layout(self):
        if not self.plan:
            return
        self.plan.calibration_points = default_calibration_layout()
        self.plan.touch()
        self._redraw()
        self._notify_change()

    # ------------------------------------------------------------ Editing
    def assign_tooth_for_selected(self):
        if not self.selected_item_id:
            return
        item = self.plan.get_item(self.selected_item_id)
        current = str(item.fdi_tooth) if item.fdi_tooth else ""
        answer = simpledialog.askstring(
            "Zahn zuweisen",
            "FDI-Zahnnummer (11-48) oder leer lassen fuer 'nicht zugeordnet':",
            initialvalue=current, parent=self,
        )
        if answer is None:
            return
        answer = answer.strip()
        if not answer:
            item.fdi_tooth = None
        else:
            try:
                tooth = int(answer)
            except ValueError:
                return
            if tooth in ALL_FDI_TEETH:
                item.fdi_tooth = tooth
        item.touch()
        self._redraw()
        self._notify_change()
