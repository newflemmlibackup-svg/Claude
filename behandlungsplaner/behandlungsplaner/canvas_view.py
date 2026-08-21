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

from . import shapes
from .fdi import ALL_FDI_TEETH, default_calibration_layout, fdi_arch, row_neighbors, teeth_between
from .models import KIND_ANCHOR_TYPE, KIND_BRUECKE, KIND_LABELS, PlanItem

HANDLE_SIZE = 9
ROTATE_HANDLE_LOCAL_Y = -0.78
SNAP_RADIUS_PX = 26
MIN_SIZE_FRACTION = 0.006
DEFAULT_NEW_WIDTH_FRACTION = 0.045

CALIB_POINT_RADIUS = 6
CALIB_COLOR = "#00c2b2"
CALIB_COLOR_SELECTED = "#00887a"
SELECTION_COLOR = "#2196f3"
HANDLE_FILL = "#ffffff"


def _try_resample():
    try:
        return Image.Resampling.LANCZOS
    except AttributeError:  # Pillow < 9.1
        return Image.LANCZOS


_RESAMPLE = _try_resample()


class PlanCanvas(tk.Canvas):
    def __init__(self, parent, **kwargs):
        kwargs.setdefault("bg", "#2b2b2b")
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

        self._drag = None
        self._external_drag_kind = None
        self._external_preview_id = None

        self.bind("<Configure>", self._on_configure)
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
        self.after_idle(self.zoom_fit)

    def _notify_change(self):
        if self.on_change:
            self.on_change()

    def _notify_selection(self):
        if self.on_selection_change:
            self.on_selection_change(self.selected_item_id)

    # --------------------------------------------------------------- View
    def _on_configure(self, _event):
        if self.plan is not None and self._photo_zoom is None:
            self.zoom_fit()
        else:
            self._redraw()

    def zoom_fit(self):
        if not self.pil_image:
            return
        cw, ch = max(self.winfo_width(), 10), max(self.winfo_height(), 10)
        self.zoom = min(cw / self.image_w, ch / self.image_h) * 0.96
        self.pan_x = (cw - self.image_w * self.zoom) / 2
        self.pan_y = (ch - self.image_h * self.zoom) / 2
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
        for item in self.plan.items:
            self._draw_item(item)
        if self.selected_item_id:
            item = self.plan.get_item(self.selected_item_id)
            if item:
                self._draw_handles(item)

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
            self.create_oval(bx - r, by - r, bx + r, by + r, fill="#2e7d32",
                              outline="#ffffff", width=1, tags=tags)
            self.create_text(bx, by, text="✓", fill="#ffffff",
                              font=("Helvetica", 9, "bold"), tags=tags)

    def _draw_calibration(self):
        for tooth, (fx, fy) in self.plan.calibration_points.items():
            cx, cy = self._frac_to_canvas(fx, fy)
            color = CALIB_COLOR
            r = CALIB_POINT_RADIUS
            self.create_oval(cx - r, cy - r, cx + r, cy + r, outline=color, width=2,
                              fill="#ffffff", tags=("calib", f"calib:{tooth}"))
            self.create_text(cx, cy - r - 9, text=str(tooth), fill=color,
                              font=("Helvetica", 9, "bold"), tags=("calib",))

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

    def _nearest_calibration_point(self, fx, fy, max_px=SNAP_RADIUS_PX):
        if not self.plan.calibration_enabled:
            return None
        best_tooth, best_dist = None, None
        px, py = self._frac_to_canvas(fx, fy)
        for tooth, (tfx, tfy) in self.plan.calibration_points.items():
            tpx, tpy = self._frac_to_canvas(tfx, tfy)
            dist = math.hypot(tpx - px, tpy - py)
            if dist <= max_px and (best_dist is None or dist < best_dist):
                best_tooth, best_dist = tooth, dist
        return best_tooth

    # ------------------------------------------------------ Maus: Auswahl
    def _on_press(self, event):
        if self._external_drag_kind:
            return  # wird ueber begin/update/end_external_drag gesteuert

        handle = self._hit_test_handle(event.x, event.y)
        if handle:
            self._start_handle_drag(handle, event)
            return

        calib_tooth = self._hit_test_calibration(event.x, event.y)
        if calib_tooth is not None:
            self._drag = {"mode": "calib", "tooth": calib_tooth}
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
        item.x, item.y = ox + dx, oy + dy
        if item.kind == KIND_BRUECKE and self._drag["orig_end"][0] is not None:
            oex, oey = self._drag["orig_end"]
            item.end_x, item.end_y = oex + dx, oey + dy
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
        snapped = self._nearest_calibration_point(fx, fy)
        if snapped is not None:
            fx, fy = self.plan.calibration_points[snapped]
        if mode == "bridge_start":
            item.x, item.y = fx, fy
            start_tooth = snapped
            end_tooth = self._nearest_calibration_point(item.end_x or 0, item.end_y or 0, max_px=1e9) \
                if self.plan.calibration_enabled else None
        else:
            item.end_x, item.end_y = fx, fy
            end_tooth = snapped
            start_tooth = self._nearest_calibration_point(item.x, item.y, max_px=1e9) \
                if self.plan.calibration_enabled else None
        if self.plan.calibration_enabled and start_tooth is not None and end_tooth is not None:
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

    # --------------------------------------------------- Palette-Drag-API
    def begin_external_drag(self, kind: str):
        self._external_drag_kind = kind

    def update_external_drag(self, canvas_x: int, canvas_y: int):
        if not self._external_drag_kind or not self.plan:
            return
        self.delete("dragpreview")
        r = 18
        inside = 0 <= canvas_x <= self.winfo_width() and 0 <= canvas_y <= self.winfo_height()
        color = SELECTION_COLOR if inside else "#888888"
        self.create_oval(canvas_x - r, canvas_y - r, canvas_x + r, canvas_y + r,
                          outline=color, width=2, dash=(3, 2), tags=("dragpreview",))
        self.create_text(canvas_x, canvas_y + r + 10, text=KIND_LABELS[self._external_drag_kind],
                          fill=color, tags=("dragpreview",))

    def end_external_drag(self, canvas_x: Optional[int], canvas_y: Optional[int]):
        kind = self._external_drag_kind
        self._external_drag_kind = None
        self.delete("dragpreview")
        if kind is None or canvas_x is None or not self.plan:
            return
        if not (0 <= canvas_x <= self.winfo_width() and 0 <= canvas_y <= self.winfo_height()):
            return
        self._place_new_item(kind, canvas_x, canvas_y)

    def _default_size_for(self, kind, width_fraction=None):
        w = width_fraction if width_fraction is not None else DEFAULT_NEW_WIDTH_FRACTION
        aspect = shapes.DEFAULT_ASPECT.get(kind, 0.8)
        h = w / aspect
        return w, h

    def _place_new_item(self, kind, canvas_x, canvas_y):
        fx, fy = self._canvas_to_frac(canvas_x, canvas_y)
        fdi_tooth = None
        width, height = self._default_size_for(kind)

        if kind == KIND_BRUECKE:
            end_x = min(fx + 0.08, 1.0)
            item = PlanItem(kind=kind, x=fx, y=fy, width=width, height=0.018,
                            end_x=end_x, end_y=fy,
                            cost=self.plan.default_cost_for(kind))
            self.plan.add_item(item)
            self.select_item(item.id)
            self._notify_change()
            return

        anchor_type = KIND_ANCHOR_TYPE.get(kind, "region")
        if anchor_type == "tooth" and self.plan.calibration_enabled:
            nearest = self._nearest_calibration_point(fx, fy)
            if nearest is not None:
                fdi_tooth = nearest
                fx, fy = self.plan.calibration_points[nearest]
                left, right = row_neighbors(nearest)
                spacing_candidates = []
                for neigh in (left, right):
                    if neigh is not None and neigh in self.plan.calibration_points:
                        nfx, nfy = self.plan.calibration_points[neigh]
                        spacing_candidates.append(math.hypot(nfx - fx, nfy - fy))
                if spacing_candidates:
                    width = min(spacing_candidates) * 0.82
                    height = width / shapes.DEFAULT_ASPECT.get(kind, 0.8)
                rotation = 180.0 if fdi_arch(nearest) == "oben" else 0.0
            else:
                rotation = 0.0
        else:
            rotation = 0.0

        item = PlanItem(
            kind=kind, x=fx, y=fy, width=width, height=height, rotation=rotation,
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
