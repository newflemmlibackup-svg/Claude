"""Hauptanwendung: verdrahtet Startbildschirm, Editor (Palette + Canvas +
Planungsliste), Menue, Undo/Redo, Speichern/Autosave und Tastenkuerzel."""
from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import Image

from . import config as config_module
from . import pdf_export, storage, theme
from .canvas_view import PlanCanvas
from .models import ALL_KINDS, KIND_LABELS, TreatmentPlan
from .palette import SymbolPalette
from .plan_list_view import PlanListView
from .start_screen import StartScreen

AUTOSAVE_INTERVAL_MS = 60_000
UNDO_STACK_SIZE = 60


class UndoStack:
    def __init__(self, max_size=UNDO_STACK_SIZE):
        self.history = []
        self.pointer = -1
        self.max_size = max_size

    def reset(self, state_json: str):
        self.history = [state_json]
        self.pointer = 0

    def push(self, state_json: str):
        if self.pointer >= 0 and self.history[self.pointer] == state_json:
            return
        self.history = self.history[: self.pointer + 1]
        self.history.append(state_json)
        if len(self.history) > self.max_size:
            self.history.pop(0)
        self.pointer = len(self.history) - 1

    def can_undo(self):
        return self.pointer > 0

    def can_redo(self):
        return self.pointer < len(self.history) - 1

    def undo(self):
        if self.can_undo():
            self.pointer -= 1
            return self.history[self.pointer]
        return None

    def redo(self):
        if self.can_redo():
            self.pointer += 1
            return self.history[self.pointer]
        return None


class NewPlanDialog(simpledialog.Dialog):
    def __init__(self, parent):
        self.result_values = None
        super().__init__(parent, title="Neuer Behandlungsplan")

    def body(self, master):
        from datetime import date
        ttk.Label(master, text="Patient/-in:").grid(row=0, column=0, sticky="w", pady=3)
        self.name_var = tk.StringVar()
        ttk.Entry(master, textvariable=self.name_var, width=30).grid(row=0, column=1, pady=3)

        ttk.Label(master, text="Geburtsdatum (JJJJ-MM-TT):").grid(row=1, column=0, sticky="w", pady=3)
        self.birth_var = tk.StringVar()
        ttk.Entry(master, textvariable=self.birth_var, width=30).grid(row=1, column=1, pady=3)

        ttk.Label(master, text="Behandler/-in:").grid(row=2, column=0, sticky="w", pady=3)
        self.practitioner_var = tk.StringVar()
        ttk.Entry(master, textvariable=self.practitioner_var, width=30).grid(row=2, column=1, pady=3)

        ttk.Label(master, text="Datum:").grid(row=3, column=0, sticky="w", pady=3)
        self.date_var = tk.StringVar(value=date.today().isoformat())
        ttk.Entry(master, textvariable=self.date_var, width=30).grid(row=3, column=1, pady=3)
        return None

    def apply(self):
        self.result_values = {
            "patient_name": self.name_var.get().strip(),
            "patient_birthdate": self.birth_var.get().strip() or None,
            "practitioner": self.practitioner_var.get().strip(),
            "plan_date": self.date_var.get().strip(),
        }


class PriceListDialog(simpledialog.Dialog):
    def __init__(self, parent, price_list: dict):
        self.price_list = price_list
        self.result_values = None
        super().__init__(parent, title="Preisliste (Standardkosten je Befundart)")

    def body(self, master):
        ttk.Label(master, text="Diese Werte werden bei neuen Positionen als\n"
                                "Vorschlag eingetragen und sind je Position frei\n"
                                "anpassbar. Keine verbindliche GOZ-/BEMA-Angabe.",
                  foreground="#555").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.vars = {}
        for i, kind in enumerate(ALL_KINDS, start=1):
            ttk.Label(master, text=KIND_LABELS[kind] + ":").grid(row=i, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=f"{self.price_list.get(kind, 0.0):.2f}")
            ttk.Entry(master, textvariable=var, width=12).grid(row=i, column=1, sticky="w", pady=2)
            self.vars[kind] = var
        return None

    def apply(self):
        result = {}
        for kind, var in self.vars.items():
            try:
                result[kind] = float(var.get().replace(",", "."))
            except ValueError:
                result[kind] = self.price_list.get(kind, 0.0)
        self.result_values = result


class BehandlungsplanerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Behandlungsplaner")
        self.root.geometry("1500x950")
        theme.apply_theme(self.root)

        self.config = config_module.load_config()
        Path(self.config["data_root"]).mkdir(parents=True, exist_ok=True)

        self.plan: TreatmentPlan | None = None
        self.pil_image: Image.Image | None = None
        self.current_folder: Path | None = None
        self.dirty = False
        self.undo_stack = UndoStack()
        self._loading = False

        self.container = tk.Frame(root, bg=theme.BG_APP)
        self.container.pack(fill="both", expand=True)

        self.start_screen = StartScreen(self.container, self.config["data_root"])
        self.start_screen.on_new = self.new_plan
        self.start_screen.on_open = self.open_plan_folder
        self.start_screen.on_duplicate = self._duplicate_plan
        self.start_screen.on_delete = self._delete_plan

        self._build_editor_frame()
        self._build_menu()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._show_start_screen()
        self.root.after(AUTOSAVE_INTERVAL_MS, self._autosave_tick)

    # --------------------------------------------------------------- UI
    def _labelled_entry(self, parent, label, variable, width):
        """Beschriftetes Eingabefeld im Kopfbereich (Label ueber dem Feld)."""
        wrap = tk.Frame(parent, bg=theme.BG_SURFACE)
        wrap.pack(side="left", padx=(0, theme.PAD_MD))
        ttk.Label(wrap, text=label, style="FieldLabel.TLabel").pack(anchor="w")
        entry = ttk.Entry(wrap, textvariable=variable, width=width, font=theme.Fonts.body)
        entry.pack(anchor="w")
        entry.bind("<FocusOut>", self._on_metadata_edited)
        return entry

    def _build_editor_frame(self):
        self.editor_frame = tk.Frame(self.container, bg=theme.BG_APP)

        header = theme.card(self.editor_frame)
        header.pack(fill="x", padx=theme.PAD_MD, pady=(theme.PAD_MD, theme.PAD_SM))

        header_inner = tk.Frame(header, bg=theme.BG_SURFACE)
        header_inner.pack(fill="x", padx=theme.PAD_MD, pady=theme.PAD_MD)

        back_wrap = tk.Frame(header_inner, bg=theme.BG_SURFACE)
        back_wrap.pack(side="left", padx=(0, theme.PAD_LG))
        ttk.Label(back_wrap, text=" ", style="FieldLabel.TLabel").pack(anchor="w")
        ttk.Button(back_wrap, text="‹  Übersicht", style="Ghost.TButton",
                   command=self._back_to_start).pack(anchor="w")

        self.patient_name_var = tk.StringVar()
        self.birthdate_var = tk.StringVar()
        self.practitioner_var = tk.StringVar()
        self.plan_date_var = tk.StringVar()

        self._labelled_entry(header_inner, "PATIENT/-IN", self.patient_name_var, 24)
        self._labelled_entry(header_inner, "GEBURTSDATUM", self.birthdate_var, 13)
        self._labelled_entry(header_inner, "BEHANDLER/-IN", self.practitioner_var, 18)
        self._labelled_entry(header_inner, "DATUM", self.plan_date_var, 13)

        calib_wrap = tk.Frame(header_inner, bg=theme.BG_SURFACE)
        calib_wrap.pack(side="left")
        ttk.Label(calib_wrap, text="ZAHNSCHEMA", style="FieldLabel.TLabel").pack(anchor="w")
        calib_row = tk.Frame(calib_wrap, bg=theme.BG_SURFACE)
        calib_row.pack(anchor="w")
        self.calib_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(calib_row, text="FDI-Raster", variable=self.calib_var,
                         command=self._on_calibration_toggle).pack(side="left")
        self.calib_edit_var = tk.BooleanVar(value=False)
        self.calib_edit_check = ttk.Checkbutton(
            calib_row, text="anpassen", variable=self.calib_edit_var,
            command=self._on_calibration_edit_toggle, state="disabled")
        self.calib_edit_check.pack(side="left", padx=(theme.PAD_SM, 0))

        self.status_label = ttk.Label(header_inner, text="", style="SurfaceMuted.TLabel")
        self.status_label.pack(side="right")

        body = tk.PanedWindow(self.editor_frame, orient="vertical", sashwidth=6,
                               bg=theme.BG_APP, bd=0, sashrelief="flat")
        body.pack(fill="both", expand=True)

        top = tk.PanedWindow(body, orient="horizontal", sashwidth=6,
                              bg=theme.BG_APP, bd=0, sashrelief="flat")
        self.palette = SymbolPalette(top, width=218)
        self.palette.on_armed_change = self._on_palette_armed_change
        top.add(self.palette, stretch="never", minsize=210)

        canvas_card = theme.card(top)
        zoom_bar = tk.Frame(canvas_card, bg=theme.BG_SURFACE)
        zoom_bar.pack(fill="x", padx=theme.PAD_SM, pady=theme.PAD_SM)
        ttk.Button(zoom_bar, text="Einpassen", style="Ghost.TButton",
                   command=lambda: self.canvas.zoom_fit()).pack(side="left")
        ttk.Button(zoom_bar, text="100 %", style="Ghost.TButton",
                   command=lambda: self.canvas.zoom_100()).pack(side="left", padx=theme.PAD_XS)
        self.hint_label = ttk.Label(zoom_bar, text="", style="SurfaceMuted.TLabel")
        self.hint_label.pack(side="right")

        self.canvas = PlanCanvas(canvas_card)
        self.canvas.pack(fill="both", expand=True, padx=1, pady=(0, 1))
        self.canvas.on_change = self._on_plan_changed
        self.canvas.on_selection_change = self._on_canvas_selection_changed
        self.canvas.on_armed_consumed = self.palette.clear_armed
        self.canvas.bind("<Button-1>", lambda e: self.canvas.focus_set(), add="+")
        self.canvas.bind("<Delete>", lambda e: self.canvas.delete_selected())
        self.canvas.bind("<BackSpace>", lambda e: self.canvas.delete_selected())
        self.canvas.bind("<Escape>", lambda e: self._cancel_armed())
        top.add(canvas_card, stretch="always")
        body.add(top, stretch="always")

        self.palette.set_target_canvas(self.canvas)

        self.list_view = PlanListView(body, height=230)
        self.list_view.on_change = self._on_plan_changed
        self.list_view.on_row_selected = self._on_list_row_selected
        body.add(self.list_view, stretch="never", minsize=200)

    def _on_palette_armed_change(self, kind):
        self.canvas.set_armed_kind(kind)
        if kind:
            self.hint_label.config(
                text=f"{KIND_LABELS[kind]}: Stelle im Bild anklicken  ·  Esc bricht ab")
        else:
            self.hint_label.config(text="")

    def _cancel_armed(self):
        self.palette.clear_armed()

    def _build_menu(self):
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Neuer Plan...", command=self.new_plan, accelerator="Ctrl+N")
        file_menu.add_command(label="Planuebersicht", command=self._back_to_start)
        file_menu.add_separator()
        file_menu.add_command(label="Speichern", command=self.save_plan, accelerator="Ctrl+S")
        file_menu.add_command(label="Als PDF exportieren...", command=self._export_pdf, accelerator="Ctrl+E")
        file_menu.add_separator()
        file_menu.add_command(label="Beenden", command=self._on_close)
        menubar.add_cascade(label="Datei", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=False)
        edit_menu.add_command(label="Rueckgaengig", command=self.undo, accelerator="Ctrl+Z")
        edit_menu.add_command(label="Wiederholen", command=self.redo, accelerator="Ctrl+Shift+Z")
        edit_menu.add_separator()
        edit_menu.add_command(label="Ausgewaehlte Position loeschen", command=lambda: self.canvas.delete_selected(),
                               accelerator="Entf")
        menubar.add_cascade(label="Bearbeiten", menu=edit_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_command(label="Einpassen", command=lambda: self.canvas.zoom_fit())
        view_menu.add_command(label="100%", command=lambda: self.canvas.zoom_100())
        menubar.add_cascade(label="Ansicht", menu=view_menu)

        settings_menu = tk.Menu(menubar, tearoff=False)
        settings_menu.add_command(label="Preisliste...", command=self._edit_price_list)
        settings_menu.add_command(label="Praxisname (fuer PDF)...", command=self._edit_clinic_name)
        settings_menu.add_command(label="Praxis-Datenordner aendern...", command=self._change_data_root)
        menubar.add_cascade(label="Einstellungen", menu=settings_menu)

        self.root.config(menu=menubar)

        self.root.bind_all("<Control-s>", lambda e: self.save_plan())
        self.root.bind_all("<Control-n>", lambda e: self.new_plan())
        self.root.bind_all("<Control-e>", lambda e: self._export_pdf())
        self.root.bind_all("<Control-z>", lambda e: self.undo())
        self.root.bind_all("<Control-Z>", lambda e: self.redo())
        self.root.bind_all("<Control-Shift-Key-Z>", lambda e: self.redo())
        self.root.bind_all("<Control-y>", lambda e: self.redo())

    # ---------------------------------------------------------- Navigation
    def _show_start_screen(self):
        if self.dirty and not self._confirm_discard_changes():
            return
        self.editor_frame.pack_forget()
        self.start_screen.refresh()
        self.start_screen.pack(fill="both", expand=True)

    def _back_to_start(self):
        self._show_start_screen()

    def _show_editor(self):
        self.start_screen.pack_forget()
        self.editor_frame.pack(fill="both", expand=True)

    # -------------------------------------------------------------- Plan
    def new_plan(self):
        path = filedialog.askopenfilename(
            title="OPG-Bild auswaehlen",
            filetypes=[
                ("Bild-/DICOM-Dateien", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.dcm"),
                ("Alle Dateien", "*.*"),
            ],
        )
        if not path:
            return
        dialog = NewPlanDialog(self.root)
        if not dialog.result_values:
            return
        values = dialog.result_values

        plan = TreatmentPlan(**values)
        folder = storage.create_plan_folder(self.config["data_root"], plan)
        try:
            filename, w, h = storage.import_image(path, folder)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Fehler beim Bildimport", str(exc))
            storage.delete_plan(folder)
            return
        plan.image_filename, plan.image_width_px, plan.image_height_px = filename, w, h
        storage.save_plan(plan, folder)
        self.open_plan_folder(folder)

    def open_plan_folder(self, folder):
        if self.dirty and not self._confirm_discard_changes():
            return
        self._loading = True
        plan = storage.load_plan(folder)
        image_path = Path(folder) / plan.image_filename
        image = Image.open(image_path).convert("RGB")

        self.plan = plan
        self.pil_image = image
        self.current_folder = Path(folder)

        self.patient_name_var.set(plan.patient_name)
        self.birthdate_var.set(plan.patient_birthdate or "")
        self.practitioner_var.set(plan.practitioner)
        self.plan_date_var.set(plan.plan_date)
        self.calib_var.set(plan.calibration_enabled)
        self.calib_edit_var.set(False)
        self.canvas.set_calibration_edit_mode(False)
        self.calib_edit_check.config(state="normal" if plan.calibration_enabled else "disabled")

        self.canvas.load(plan, image)
        self.list_view.refresh(plan)
        self.undo_stack.reset(json.dumps(plan.to_dict()))
        self.dirty = False
        self._update_title()
        self._show_editor()
        self._loading = False

    def _duplicate_plan(self, folder):
        new_folder = storage.duplicate_plan(folder, self.config["data_root"])
        self.start_screen.refresh()
        self.open_plan_folder(new_folder)

    def _delete_plan(self, folder):
        storage.delete_plan(folder)

    # ------------------------------------------------------------ Speichern
    def save_plan(self):
        if not self.plan or not self.current_folder:
            return
        storage.save_plan(self.plan, self.current_folder)
        self.dirty = False
        self._update_title()

    def _autosave_tick(self):
        if self.dirty and self.plan and self.current_folder:
            self.save_plan()
        self.root.after(AUTOSAVE_INTERVAL_MS, self._autosave_tick)

    def _mark_dirty(self):
        self.dirty = True
        self._update_title()

    def _update_title(self):
        name = self.plan.patient_name if self.plan else ""
        marker = "*" if self.dirty else ""
        suffix = f" - {name}{marker}" if self.plan else ""
        self.root.title(f"Behandlungsplaner{suffix}")

    def _confirm_discard_changes(self) -> bool:
        answer = messagebox.askyesnocancel(
            "Ungespeicherte Aenderungen",
            "Es gibt ungespeicherte Aenderungen. Jetzt speichern?",
        )
        if answer is None:
            return False
        if answer:
            self.save_plan()
        else:
            self.dirty = False
        return True

    # ------------------------------------------------------------- Events
    def _on_plan_changed(self):
        if self._loading or not self.plan:
            return
        self._mark_dirty()
        self.undo_stack.push(json.dumps(self.plan.to_dict()))
        self.list_view.refresh(self.plan)

    def _on_metadata_edited(self, _event):
        if self._loading or not self.plan:
            return
        self.plan.patient_name = self.patient_name_var.get().strip()
        self.plan.patient_birthdate = self.birthdate_var.get().strip() or None
        self.plan.practitioner = self.practitioner_var.get().strip()
        self.plan.plan_date = self.plan_date_var.get().strip()
        self._on_plan_changed()

    def _on_canvas_selection_changed(self, item_id):
        self.list_view.select_row(item_id)

    def _on_list_row_selected(self, item_id):
        self.canvas.select_item(item_id)

    def _on_calibration_toggle(self):
        if not self.plan:
            return
        enabled = self.calib_var.get()
        self.canvas.set_calibration_enabled(enabled)
        self.calib_edit_check.config(state="normal" if enabled else "disabled")
        if not enabled and self.calib_edit_var.get():
            self.calib_edit_var.set(False)
            self._on_calibration_edit_toggle()

    def _on_calibration_edit_toggle(self):
        if not self.plan:
            return
        editing = self.calib_edit_var.get()
        self.canvas.set_calibration_edit_mode(editing)
        if editing:
            self.palette.clear_armed()
            self.hint_label.config(
                text="Kalibrieren: Zahlenpunkte auf die Zähne ziehen  ·  danach „anpassen“ beenden")
        else:
            self.hint_label.config(text="")

    # ---------------------------------------------------------- Undo/Redo
    def _load_snapshot(self, state_json):
        restored = TreatmentPlan.from_dict(json.loads(state_json))
        self.plan = restored
        self.canvas.plan = restored
        self.canvas.selected_item_id = None
        self.canvas._redraw()
        self.list_view.refresh(restored)
        self.calib_var.set(restored.calibration_enabled)
        self.patient_name_var.set(restored.patient_name)
        self.birthdate_var.set(restored.patient_birthdate or "")
        self.practitioner_var.set(restored.practitioner)
        self.plan_date_var.set(restored.plan_date)
        self._mark_dirty()

    def undo(self):
        if not self.plan:
            return
        state = self.undo_stack.undo()
        if state is not None:
            self._load_snapshot(state)

    def redo(self):
        if not self.plan:
            return
        state = self.undo_stack.redo()
        if state is not None:
            self._load_snapshot(state)

    # ------------------------------------------------------------- Export
    def _export_pdf(self):
        if not self.plan or not self.pil_image:
            messagebox.showinfo("Kein Plan geoeffnet", "Bitte zuerst einen Plan oeffnen.")
            return
        default_name = f"Behandlungsplan_{self.plan.patient_name or 'Patient'}_{self.plan.plan_date}.pdf"
        default_name = default_name.replace("/", "_").replace(" ", "_")
        path = filedialog.asksaveasfilename(
            title="PDF exportieren", defaultextension=".pdf", initialfile=default_name,
            filetypes=[("PDF-Dateien", "*.pdf")],
        )
        if not path:
            return
        try:
            pdf_export.export_pdf(self.plan, self.pil_image, path, clinic_name=self.config.get("clinic_name", ""))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Fehler beim PDF-Export", str(exc))
            return
        messagebox.showinfo("PDF exportiert", f"Der Behandlungsplan wurde gespeichert unter:\n{path}")

    # ---------------------------------------------------------- Einstellungen
    def _edit_price_list(self):
        if not self.plan:
            messagebox.showinfo("Kein Plan geoeffnet", "Bitte zuerst einen Plan oeffnen.")
            return
        dialog = PriceListDialog(self.root, self.plan.price_list)
        if dialog.result_values:
            self.plan.price_list = dialog.result_values
            self._on_plan_changed()

    def _edit_clinic_name(self):
        name = simpledialog.askstring("Praxisname", "Praxisname (erscheint im PDF-Kopf):",
                                       initialvalue=self.config.get("clinic_name", ""), parent=self.root)
        if name is not None:
            self.config["clinic_name"] = name.strip()
            config_module.save_config(self.config)

    def _change_data_root(self):
        path = filedialog.askdirectory(title="Praxis-Datenordner waehlen",
                                        initialdir=self.config["data_root"])
        if not path:
            return
        self.config["data_root"] = path
        config_module.save_config(self.config)
        self.start_screen.data_root = path
        self.start_screen.refresh()

    def _on_close(self):
        if self.dirty and not self._confirm_discard_changes():
            return
        self.root.destroy()


def main():
    root = tk.Tk()
    BehandlungsplanerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
