"""Bedienoberfläche (Tkinter) des DVT-Sidexis-Importers.

Ablauf in der Praxis:
  1. Fremden USB-Stick einstecken - er wird erkannt und automatisch analysiert.
  2. Gefundene Aufnahmen prüfen, Patientendaten bei Bedarf anpassen.
  3. "Für Sidexis aufbereiten" klicken und den Ergebnisordner in Sidexis importieren.
"""
from __future__ import annotations

import datetime as dt
import queue
import re
import shutil
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .converter import FLAT_SUFFIX, ConversionError, convert_series_list, validate_patient
from .drives import list_removable_drives, open_in_file_manager
from .scanner import KIND_VOLUME, scan_source

CHECK_ON = "☑"
CHECK_OFF = "☐"
SEX_LABELS = {"": "", "M": "männlich", "F": "weiblich", "O": "divers"}
SEX_CODES = {v: k for k, v in SEX_LABELS.items()}
DRIVE_POLL_MS = 2000


class _Cancelled(Exception):
    pass


def format_date(value: str) -> str:
    """JJJJMMTT -> TT.MM.JJJJ (unbekannte Formate bleiben unverändert)."""
    if re.fullmatch(r"\d{8}", value or ""):
        return f"{value[6:8]}.{value[4:6]}.{value[0:4]}"
    return value or ""


def parse_date(text: str) -> str:
    """TT.MM.JJJJ (auch T.M.JJ, TTMMJJJJ) -> JJJJMMTT. Ungültiges bleibt als Text erhalten."""
    text = (text or "").strip()
    if not text:
        return ""
    m = re.fullmatch(r"(\d{1,2})[.\-/ ](\d{1,2})[.\-/ ](\d{2}|\d{4})", text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
        if len(year) == 2:
            now = dt.date.today().year % 100
            year = ("20" if int(year) <= now else "19") + year
        return f"{int(year):04d}{month:02d}{day:02d}"
    if re.fullmatch(r"\d{8}", text):
        if int(text[4:6]) > 12 or int(text[:4]) < 1800:   # TTMMJJJJ
            return f"{text[4:8]}{text[2:4]}{text[0:2]}"
        return text
    return text


def default_output_base() -> Path:
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / "DVT-Sidexis-Import"


def output_folder_name(patient) -> str:
    name = "_".join(p for p in (patient.last_name, patient.first_name) if p.strip()) or "Patient"
    name = re.sub(r"[^\w\-]+", "_", name, flags=re.UNICODE).strip("_") or "Patient"
    return f"{name}_{dt.datetime.now():%Y%m%d-%H%M%S}"


class DvtImporterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"DVT-Sidexis-Importer {__version__}")
        self.geometry("1100x760")
        self.minsize(940, 640)

        self.source_dir: Path | None = None
        self.output_base: Path = default_output_base()
        self.last_output: Path | None = None
        self.scan_result = None
        self.selected_keys: set = set()
        self.row_to_series: dict = {}
        self.current_series = None
        self._loading_form = False
        self._busy = False
        self._cancel = threading.Event()
        self._queue: "queue.Queue" = queue.Queue()
        self._drives: list = []
        self._known_drive_paths: set | None = None

        self._build_widgets()
        self._refresh_drives()
        self.after(100, self._poll_queue)

    # ================================================================== Aufbau
    def _build_widgets(self):
        style = ttk.Style(self)
        if sys.platform not in ("win32", "darwin"):
            try:
                style.theme_use("clam")
            except tk.TclError:
                pass
        style.configure("Step.TLabelframe.Label", font=("", 11, "bold"))
        style.configure("Big.TButton", font=("", 12, "bold"), padding=(18, 10))
        style.configure("Hint.TLabel", foreground="#666666")
        style.configure("Treeview", rowheight=26)

        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)

        # ---------------------------------------------------- 1 Quelle
        f1 = ttk.LabelFrame(outer, text="1  Fremde Aufnahme (USB-Stick, CD oder Ordner)",
                            style="Step.TLabelframe", padding=8)
        f1.pack(fill="x")
        row = ttk.Frame(f1)
        row.pack(fill="x")
        self.source_var = tk.StringVar()
        self.source_combo = ttk.Combobox(row, textvariable=self.source_var, state="readonly")
        self.source_combo.pack(side="left", fill="x", expand=True)
        self.source_combo.bind("<<ComboboxSelected>>", self._on_drive_selected)
        ttk.Button(row, text="Anderen Ordner wählen …", command=self._choose_source).pack(side="left", padx=(8, 0))
        self.scan_btn = ttk.Button(row, text="Analysieren", command=self._scan_or_cancel, state="disabled")
        self.scan_btn.pack(side="left", padx=(8, 0))
        self.auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(f1, text="Neu eingesteckte Datenträger automatisch analysieren",
                        variable=self.auto_var).pack(anchor="w", pady=(6, 0))

        # ---------------------------------------------------- 2 Aufnahmen
        f2 = ttk.LabelFrame(outer, text="2  Gefundene Aufnahmen prüfen und Patientendaten einstellen",
                            style="Step.TLabelframe", padding=8)
        f2.pack(fill="both", expand=True, pady=(10, 0))
        f2.columnconfigure(0, weight=3)
        f2.columnconfigure(2, weight=2)
        f2.rowconfigure(0, weight=1)

        columns = ("check", "patient", "type", "size", "missing")
        self.tree = ttk.Treeview(f2, columns=columns, show="headings", selectmode="browse", height=7)
        for col, text, width, anchor, stretch in (
            ("check", "", 34, "center", False),
            ("patient", "Patient", 210, "w", True),
            ("type", "Art", 120, "w", False),
            ("size", "Größe (B × H × Schichten)", 190, "w", False),
            ("missing", "Fehlend", 80, "center", False),
        ):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=anchor, stretch=stretch)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        sb = ttk.Scrollbar(f2, orient="vertical", command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)

        self.notes_text = tk.Text(f2, height=5, wrap="word", state="disabled", relief="flat",
                                  background=self.cget("background"), font=("", 10))
        self.notes_text.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        form = ttk.Frame(f2, padding=(14, 0, 0, 0))
        form.grid(row=0, column=2, rowspan=2, sticky="nsew")
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="Patientendaten für Sidexis", font=("", 10, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.form_vars: dict = {}
        self.form_widgets: list = []
        fields = (
            ("last_name", "Nachname"), ("first_name", "Vorname"),
            ("birth_date", "Geburtsdatum (TT.MM.JJJJ)"), ("sex", "Geschlecht"),
            ("patient_id", "Patienten-Nr."), ("study_date", "Aufnahmedatum (TT.MM.JJJJ)"),
            ("description", "Bezeichnung der Aufnahme"),
        )
        for r, (name, label) in enumerate(fields, start=1):
            ttk.Label(form, text=label).grid(row=r, column=0, sticky="w", pady=3, padx=(0, 8))
            var = tk.StringVar()
            if name == "sex":
                widget = ttk.Combobox(form, textvariable=var, state="disabled",
                                      values=list(SEX_LABELS.values()))
            else:
                widget = ttk.Entry(form, textvariable=var, state="disabled")
            widget.grid(row=r, column=1, sticky="ew", pady=3)
            var.trace_add("write", lambda *_a, n=name: self._on_form_change(n))
            self.form_vars[name] = var
            self.form_widgets.append(widget)
        self.apply_all_btn = ttk.Button(form, text="Patientendaten für alle Aufnahmen übernehmen",
                                        command=self._apply_patient_to_all, state="disabled")
        self.apply_all_btn.grid(row=len(fields) + 1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Label(form, style="Hint.TLabel", wraplength=330, justify="left",
                  text="Tipp: Name und Geburtsdatum genau so eintragen, wie der Patient "
                       "in Sidexis angelegt ist.").grid(
            row=len(fields) + 2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        # ---------------------------------------------------- 3 Ausgabe
        f3 = ttk.LabelFrame(outer, text="3  Für Sidexis aufbereiten", style="Step.TLabelframe", padding=8)
        f3.pack(fill="x", pady=(10, 0))
        row = ttk.Frame(f3)
        row.pack(fill="x")
        ttk.Label(row, text="Speicherort:").pack(side="left")
        self.dest_var = tk.StringVar(value=str(self.output_base))
        ttk.Entry(row, textvariable=self.dest_var, state="readonly").pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row, text="Ändern …", command=self._choose_dest).pack(side="left")
        row = ttk.Frame(f3)
        row.pack(fill="x", pady=(8, 0))
        self.flat_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, variable=self.flat_var,
                        text="Zusätzlich einfache .dcm-Einzeldateien schreiben (für andere Programme)"
                        ).pack(side="left")
        self.convert_btn = ttk.Button(row, text="Für Sidexis aufbereiten", style="Big.TButton",
                                      command=self._convert_or_cancel, state="disabled")
        self.convert_btn.pack(side="right")
        self.open_btn = ttk.Button(row, text="Ergebnisordner öffnen", command=self._open_output, state="disabled")
        self.open_btn.pack(side="right", padx=8)

        # ---------------------------------------------------- Fortschritt
        self.progress = ttk.Progressbar(outer, mode="determinate")
        self.progress.pack(fill="x", pady=(10, 4))
        self.status_var = tk.StringVar(value="Bereit. Bitte USB-Stick einstecken oder Ordner wählen.")
        ttk.Label(outer, textvariable=self.status_var).pack(anchor="w")
        log_frame = ttk.Frame(outer)
        log_frame.pack(fill="x", pady=(4, 0))
        self.log_text = tk.Text(log_frame, height=6, state="disabled", wrap="word", font=("", 9))
        self.log_text.pack(side="left", fill="x", expand=True)
        lsb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        lsb.pack(side="left", fill="y")
        self.log_text.configure(yscrollcommand=lsb.set)

    # ============================================================ Datenträger
    def _refresh_drives(self):
        drives = list_removable_drives()
        paths = {d.path for d in drives}
        new = [] if self._known_drive_paths is None else [d for d in drives if d.path not in self._known_drive_paths]
        first_run = self._known_drive_paths is None
        self._known_drive_paths = paths
        if [d.path for d in drives] != [d.path for d in self._drives]:
            self._drives = drives
            self.source_combo.configure(values=[d.display for d in drives])
        if not self._busy:
            if new:
                self._set_source(Path(new[0].path), new[0].display)
                if self.auto_var.get():
                    self._log(f"Neuer Datenträger erkannt: {new[0].display}")
                    self._start_scan()
            elif first_run and drives and self.source_dir is None:
                self._set_source(Path(drives[0].path), drives[0].display)
            elif self.source_dir is None and not drives:
                self.source_var.set("Kein Wechseldatenträger gefunden – bitte einstecken oder Ordner wählen")
        self.after(DRIVE_POLL_MS, self._refresh_drives)

    def _on_drive_selected(self, _event=None):
        idx = self.source_combo.current()
        if 0 <= idx < len(self._drives):
            self._set_source(Path(self._drives[idx].path), self._drives[idx].display)

    def _choose_source(self):
        path = filedialog.askdirectory(title="Ordner mit der fremden DVT-Aufnahme wählen")
        if path:
            self._set_source(Path(path), path)
            self._start_scan()

    def _set_source(self, path: Path, display: str):
        self.source_dir = path
        self.source_var.set(display)
        if not self._busy:
            self.scan_btn.config(state="normal")

    # ================================================================ Analyse
    def _scan_or_cancel(self):
        if self._busy:
            self._cancel.set()
        else:
            self._start_scan()

    def _start_scan(self):
        if not self.source_dir or self._busy:
            return
        self._clear_results()
        self._set_busy("scan")
        self._log(f"Analysiere {self.source_dir} …")
        self.progress.config(mode="indeterminate")
        self.progress.start(15)
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        def progress(msg):
            if self._cancel.is_set():
                raise _Cancelled()
            self._queue.put(("STATUS", msg))

        try:
            result = scan_source(self.source_dir, progress_cb=progress)
            self._queue.put(("SCAN_RESULT", result))
        except _Cancelled:
            self._queue.put(("LOG", "Analyse abgebrochen."))
        except Exception as exc:  # noqa: BLE001
            self._queue.put(("ERROR", f"Fehler bei der Analyse: {exc}"))
        self._queue.put(("DONE", None))

    def _clear_results(self):
        self.tree.delete(*self.tree.get_children())
        self.row_to_series.clear()
        self.selected_keys.clear()
        self.scan_result = None
        self._show_series(None)

    def _populate_tree(self, result):
        self.scan_result = result
        self._clear_tree_only()
        if not result.series:
            self._log("Keine DICOM-Bilder gefunden.")
            messagebox.showwarning(
                "Keine Aufnahmen gefunden",
                "Auf diesem Datenträger wurden keine lesbaren DICOM-Bilder gefunden.\n\n"
                "Bitte prüfen, ob der richtige Stick/Ordner gewählt ist. Manche Praxen geben die "
                "Aufnahme als ZIP-Datei mit – diese muss zuerst entpackt werden.")
            return
        for series in result.series:
            row = self.tree.insert("", "end", values=self._row_values(series, False))
            self.row_to_series[row] = series
            if series.kind == KIND_VOLUME:
                self.selected_keys.add(series.key)
                self.tree.set(row, "check", CHECK_ON)
        volumes = sum(1 for s in result.series if s.kind == KIND_VOLUME)
        self._log(f"{volumes} DVT-Volumen gefunden ({result.total_files_seen} Dateien geprüft, "
                  f"{result.skipped_files} sonstige Dateien ignoriert).")
        for series in result.series:
            if series.num_missing:
                self._log(f"  {series.patient.display_name}: {series.num_missing} Schicht(en) fehlen – "
                          "werden schwarz ergänzt.")
        first = next(iter(self.row_to_series))
        self.tree.selection_set(first)
        self.tree.focus(first)
        self._update_convert_state()

    def _clear_tree_only(self):
        self.tree.delete(*self.tree.get_children())
        self.row_to_series.clear()
        self.selected_keys.clear()

    def _row_values(self, series, checked: bool):
        return (
            CHECK_ON if checked else CHECK_OFF,
            series.patient.display_name,
            "DVT-Volumen" if series.kind == KIND_VOLUME else "Einzelbild(er)",
            series.size_label,
            series.num_missing or "–",
        )

    # ================================================= Auswahl + Patientendaten
    def _on_tree_click(self, event):
        if self.tree.identify("region", event.x, event.y) != "cell":
            return
        row = self.tree.identify_row(event.y)
        if row and self.tree.identify_column(event.x) == "#1" and not self._busy:
            series = self.row_to_series[row]
            if series.key in self.selected_keys:
                self.selected_keys.discard(series.key)
                self.tree.set(row, "check", CHECK_OFF)
            else:
                self.selected_keys.add(series.key)
                self.tree.set(row, "check", CHECK_ON)
            self._update_convert_state()

    def _on_tree_select(self, _event=None):
        sel = self.tree.selection()
        self._show_series(self.row_to_series.get(sel[0]) if sel else None)

    def _show_series(self, series):
        self.current_series = series
        self._loading_form = True
        state = "normal" if series is not None else "disabled"
        for widget in self.form_widgets:
            widget.config(state=("readonly" if isinstance(widget, ttk.Combobox) else "normal")
                          if series is not None else "disabled")
        self.apply_all_btn.config(state=state if len(self.row_to_series) > 1 else "disabled")
        p = series.patient if series is not None else None
        for name, var in self.form_vars.items():
            value = getattr(p, name) if p is not None else ""
            if name in ("birth_date", "study_date"):
                value = format_date(value)
            elif name == "sex":
                value = SEX_LABELS.get(value, "")
            var.set(value)
        self._loading_form = False

        lines = []
        if series is not None:
            device = " ".join(x for x in (series.manufacturer, series.model) if x)
            if device:
                lines.append(f"Gerät: {device}")
            if series.plan is not None:
                ps, ss = series.plan.pixel_spacing, series.plan.slice_spacing
                lines.append(f"Voxelgröße: {ps[1]:.3g} × {ps[0]:.3g} × {ss:.3g} mm")
            lines.extend(f"• {w}" for w in series.warnings)
        self.notes_text.config(state="normal")
        self.notes_text.delete("1.0", "end")
        self.notes_text.insert("end", "\n".join(lines))
        self.notes_text.config(state="disabled")

    def _on_form_change(self, name: str):
        if self._loading_form or self.current_series is None:
            return
        value = self.form_vars[name].get().strip()
        if name in ("birth_date", "study_date"):
            value = parse_date(value)
        elif name == "sex":
            value = SEX_CODES.get(value, "")
        setattr(self.current_series.patient, name, value)
        if name in ("last_name", "first_name"):
            for row, series in self.row_to_series.items():
                if series is self.current_series:
                    self.tree.set(row, "patient", series.patient.display_name)

    def _apply_patient_to_all(self):
        if self.current_series is None:
            return
        src = self.current_series.patient
        for row, series in self.row_to_series.items():
            for name in ("last_name", "first_name", "birth_date", "sex", "patient_id"):
                setattr(series.patient, name, getattr(src, name))
            self.tree.set(row, "patient", series.patient.display_name)
        self._log("Patientendaten für alle Aufnahmen übernommen.")

    # ============================================================= Aufbereiten
    def _choose_dest(self):
        path = filedialog.askdirectory(title="Speicherort für aufbereitete Aufnahmen wählen")
        if path:
            self.output_base = Path(path)
            self.dest_var.set(path)

    def _selected_series(self):
        if not self.scan_result:
            return []
        return [s for s in self.scan_result.series if s.key in self.selected_keys]

    def _update_convert_state(self):
        ok = bool(self.selected_keys) and not self._busy
        self.convert_btn.config(state="normal" if ok or self._busy == "convert" else "disabled")

    def _convert_or_cancel(self):
        if self._busy == "convert":
            self._cancel.set()
            return
        selected = self._selected_series()
        if not selected or self._busy:
            return
        for series in selected:
            errors = validate_patient(series.patient)
            if errors:
                messagebox.showerror("Eingabe prüfen", f"{series.patient.display_name}:\n" + "\n".join(errors))
                return
        if any(not s.patient.last_name.strip() for s in selected):
            if not messagebox.askyesno(
                    "Patientenname fehlt",
                    "Bei mindestens einer Aufnahme ist kein Nachname eingetragen.\n"
                    "Sie wird dann unter „Unbekannt“ gespeichert.\n\nTrotzdem fortfahren?"):
                return
        out_dir = self.output_base / output_folder_name(selected[0].patient)
        self.last_output = None
        self.open_btn.config(state="disabled")
        self._set_busy("convert")
        self.progress.config(mode="determinate", value=0, maximum=100)
        self._log(f"Bereite {len(selected)} Aufnahme(n) auf → {out_dir}")
        threading.Thread(target=self._convert_worker, args=(selected, out_dir, self.flat_var.get()),
                         daemon=True).start()

    def _convert_worker(self, selected, out_dir: Path, flat: bool):
        def progress(done, total):
            if self._cancel.is_set():
                raise _Cancelled()
            self._queue.put(("PROGRESS", (done, total)))

        try:
            result = convert_series_list(selected, out_dir, log=lambda m: self._queue.put(("LOG", m)),
                                         progress_cb=progress, write_flat_copy=flat)
            self._queue.put(("CONVERT_RESULT", result))
        except _Cancelled:
            self._cleanup(out_dir)
            self._queue.put(("LOG", "Aufbereitung abgebrochen."))
        except ConversionError as exc:
            self._cleanup(out_dir)
            self._queue.put(("ERROR", str(exc)))
        except Exception as exc:  # noqa: BLE001
            self._cleanup(out_dir)
            self._queue.put(("ERROR", f"Fehler bei der Aufbereitung: {exc}"))
        self._queue.put(("DONE", None))

    @staticmethod
    def _cleanup(out_dir: Path):
        for path in (out_dir, out_dir.parent / (out_dir.name + FLAT_SUFFIX)):
            shutil.rmtree(path, ignore_errors=True)

    def _on_convert_done(self, result):
        self.last_output = result.output_dir
        self.open_btn.config(state="normal")
        for line in result.per_series_log:
            self._log(f"  {line}")
        for line in result.problems:
            self._log(f"  HINWEIS: {line}")

        lines = [f"{result.images_written} Bilder aus {result.series_converted} Aufnahme(n) wurden gespeichert."]
        black = result.black_missing + result.black_damaged
        if black:
            lines.append(f"\n{black} fehlende/unlesbare Schicht(en) wurden durch schwarze Schichten ersetzt.")
        if result.partially_damaged:
            lines.append(f"{result.partially_damaged} abgeschnittene Schicht(en) wurden teilweise schwarz aufgefüllt.")
        if result.problems:
            lines.append("\nHinweise:\n" + "\n".join(f"• {p}" for p in result.problems))
        lines.append(f"\nErgebnisordner:\n{result.output_dir}")
        lines.append("\nIn Sidexis den DICOM-Import aufrufen und diesen Ordner "
                     "(bzw. die Datei DICOMDIR darin) auswählen.")
        self.status_var.set("Fertig." if result.verified else "Fertig – bitte Hinweise beachten.")
        (messagebox.showinfo if result.verified else messagebox.showwarning)(
            "Aufbereitung abgeschlossen", "\n".join(lines))

    def _open_output(self):
        if self.last_output:
            open_in_file_manager(self.last_output)

    # ================================================================ Zustand
    def _set_busy(self, what):
        self._busy = what
        if what:
            self._cancel.clear()
        self.scan_btn.config(text="Abbrechen" if what == "scan" else "Analysieren",
                             state="normal" if what == "scan" or (not what and self.source_dir) else "disabled")
        self.convert_btn.config(text="Abbrechen" if what == "convert" else "Für Sidexis aufbereiten")
        self._update_convert_state()

    def _log(self, message: str):
        self.status_var.set(message.strip())
        self.log_text.config(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _handle(self, kind, payload):
        if kind == "STATUS":
            self.status_var.set(payload)
        elif kind == "LOG":
            self._log(payload)
        elif kind == "ERROR":
            self._log(payload)
            messagebox.showerror("Fehler", payload)
        elif kind == "PROGRESS":
            done, total = payload
            self.progress.config(maximum=max(total, 1), value=done)
            self.status_var.set(f"Schicht {done} von {total} …")
        elif kind == "SCAN_RESULT":
            self._populate_tree(payload)
        elif kind == "CONVERT_RESULT":
            self._on_convert_done(payload)
        elif kind == "DONE":
            self.progress.stop()
            self.progress.config(mode="determinate", value=0)
            self._set_busy(False)

    def _poll_queue(self):
        try:
            while True:
                self._handle(*self._queue.get_nowait())
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)


def main():
    if sys.platform == "win32":
        try:  # scharfe Darstellung auf hochauflösenden Bildschirmen
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    app = DvtImporterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
