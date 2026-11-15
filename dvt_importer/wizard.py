"""„Felix ist nicht da“-Modus: führt Schritt für Schritt mit einfachen Fragen durch
den gesamten Ablauf - ohne Fachbegriffe, immer nur eine Entscheidung pro Seite.
"""
from __future__ import annotations

import queue
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .converter import FLAT_SUFFIX, convert_series_list, validate_patient
from .drives import list_removable_drives, open_in_file_manager
from .preview import PreviewPanel
from .scanner import KIND_VOLUME, scan_source

MODE_NAME = "Felix ist nicht da-Modus"
ACCENT = "#e8590c"
STEPS = ("Stick wählen", "Aufnahme ansehen", "Patient", "Speicherort", "Fertigstellen")


class _Cancelled(Exception):
    pass


class WizardWindow(tk.Toplevel):
    def __init__(self, parent, output_base: Path):
        super().__init__(parent)
        from .gui import format_date, output_folder_name, parse_date  # hier wegen Kreisimport

        self._format_date, self._parse_date, self._folder_name = format_date, parse_date, output_folder_name
        self.title(MODE_NAME)
        from .gui import screen_size

        screen_w, screen_h = screen_size(self)
        width, height = min(980, screen_w - 40), min(700, screen_h - 110)
        self.geometry(f"{width}x{height}+{max(0, (screen_w - width) // 2)}+{max(0, (screen_h - height) // 3)}")
        self.minsize(min(900, width), min(600, height))

        self.default_base = Path(output_base)
        self.output_base = Path(output_base)
        self.source: Path | None = None
        self.source_label = ""
        self.custom_folder: Path | None = None
        self.scan_result = None
        self.volumes: list = []
        self.checked: dict = {}
        self.patient_vars: dict = {}
        self.result = None
        self.step = 0
        self._queue: "queue.Queue" = queue.Queue()
        self._cancel = threading.Event()
        self._busy = False
        self._drive_job = None
        self.preview: PreviewPanel | None = None

        self._build_frame()
        self._show_source()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.transient(parent)
        self.after(100, self._poll)
        try:
            self.grab_set()
        except tk.TclError:
            pass

    # ================================================================ Rahmen
    def _build_frame(self):
        style = ttk.Style(self)
        style.configure("WizTitle.TLabel", font=("", 20, "bold"))
        style.configure("WizText.TLabel", font=("", 13))
        style.configure("WizHint.TLabel", font=("", 11), foreground="#666666")
        style.configure("WizWarn.TLabel", font=("", 12, "bold"), foreground="#c92a2a")
        style.configure("WizOk.TLabel", font=("", 12, "bold"), foreground="#2b8a3e")
        style.configure("Wiz.TRadiobutton", font=("", 13))
        style.configure("Wiz.TCheckbutton", font=("", 13))
        style.configure("Wiz.TButton", font=("", 12), padding=(14, 8))
        style.configure("WizNext.TButton", font=("", 13, "bold"), padding=(22, 10))

        head = tk.Frame(self, background=ACCENT)
        head.pack(fill="x")
        tk.Label(head, text=MODE_NAME, background=ACCENT, foreground="white",
                 font=("", 13, "bold")).pack(side="left", padx=16, pady=8)
        self.step_label = tk.Label(head, background=ACCENT, foreground="white", font=("", 12))
        self.step_label.pack(side="right", padx=16)

        self.nav = ttk.Frame(self, padding=(24, 10, 24, 18))
        self.nav.pack(side="bottom", fill="x")
        self.back_btn = ttk.Button(self.nav, text="‹  Zurück", style="Wiz.TButton")
        self.back_btn.pack(side="left")
        self.next_btn = ttk.Button(self.nav, text="Weiter  ›", style="WizNext.TButton")
        self.next_btn.pack(side="right")
        ttk.Separator(self).pack(side="bottom", fill="x")

        self.body = ttk.Frame(self, padding=(32, 22, 32, 10))
        self.body.pack(fill="both", expand=True)

    def _page(self, step: int, title: str, text: str = ""):
        """Leert die Seite und setzt Überschrift, Erklärtext und Schrittanzeige."""
        if self._drive_job is not None:
            self.after_cancel(self._drive_job)
            self._drive_job = None
        self.preview = None
        for child in self.body.winfo_children():
            child.destroy()
        self.step = step
        self.step_label.config(text=f"Schritt {step + 1} von {len(STEPS)}:  {STEPS[step]}")
        ttk.Label(self.body, text=title, style="WizTitle.TLabel", wraplength=880,
                  justify="left").pack(anchor="w")
        if text:
            ttk.Label(self.body, text=text, style="WizText.TLabel", wraplength=880,
                      justify="left").pack(anchor="w", pady=(8, 0))
        content = ttk.Frame(self.body)
        content.pack(fill="both", expand=True, pady=(18, 0))
        return content

    def _nav(self, back=None, nxt=None, next_text="Weiter  ›", next_enabled=True):
        self.back_btn.config(command=back or (lambda: None), state="normal" if back else "disabled")
        self.next_btn.config(text=next_text, command=nxt or (lambda: None),
                             state="normal" if nxt and next_enabled else "disabled")

    # ===================================================== Schritt 1: Quelle
    def _show_source(self):
        c = self._page(0, "Wo ist die fremde Aufnahme?",
                       "Stecken Sie den USB-Stick (oder die CD) des Patienten in den Computer. "
                       "Er erscheint nach ein paar Sekunden hier in der Liste. Klicken Sie ihn an.")
        self.source_var = tk.StringVar(value=str(self.source) if self.source else "")
        self.drive_box = ttk.Frame(c)
        self.drive_box.pack(fill="x")
        self._shown_drives = None
        ttk.Separator(c).pack(fill="x", pady=18)
        ttk.Label(c, style="WizText.TLabel", wraplength=880, justify="left",
                  text="Liegt die Aufnahme stattdessen schon in einem Ordner auf dem Computer?").pack(anchor="w")
        ttk.Button(c, text="Ordner auf dem Computer auswählen …", style="Wiz.TButton",
                   command=self._pick_source_folder).pack(anchor="w", pady=(8, 0))
        self._nav(nxt=self._start_scan, next_enabled=bool(self.source))
        self._refresh_drives()

    def _refresh_drives(self):
        drives = list_removable_drives()
        entries = [(d.path, d.display) for d in drives]
        if self.custom_folder is not None:
            entries.append((str(self.custom_folder), f"Ordner:  {self.custom_folder}"))
        if entries != self._shown_drives:
            self._shown_drives = entries
            for child in self.drive_box.winfo_children():
                child.destroy()
            if not entries:
                ttk.Label(self.drive_box, style="WizHint.TLabel", font=("", 13),
                          text="⏳  Noch kein USB-Stick erkannt – bitte einstecken und kurz warten …"
                          ).pack(anchor="w", pady=6)
            for path, label in entries:
                ttk.Radiobutton(self.drive_box, text=label, value=path, variable=self.source_var,
                                style="Wiz.TRadiobutton", command=self._on_source_pick
                                ).pack(anchor="w", pady=5)
            paths = [p for p, _l in entries]
            if self.source_var.get() not in paths:
                # Genau ein Stick vorhanden -> gleich vorauswählen.
                self.source_var.set(paths[0] if len(paths) == 1 else "")
            self._on_source_pick()
        self._drive_job = self.after(1500, self._refresh_drives)

    def _on_source_pick(self):
        value = self.source_var.get()
        self.source = Path(value) if value else None
        self.source_label = dict(self._shown_drives or []).get(value, value)
        self.next_btn.config(state="normal" if value else "disabled")

    def _pick_source_folder(self):
        path = filedialog.askdirectory(parent=self, title="Ordner mit der fremden Aufnahme auswählen")
        if path:
            self.custom_folder = Path(path)
            self.source_var.set(path)
            self._shown_drives = None
            if self._drive_job is not None:
                self.after_cancel(self._drive_job)
            self._refresh_drives()

    # ------------------------------------------------------------- Analyse
    def _start_scan(self):
        if not self.source:
            return
        c = self._page(1, "Einen Moment bitte …",
                       f"Der Datenträger wird durchsucht:  {self.source_label}\n"
                       "Das kann bei großen Sticks oder CDs einige Minuten dauern.")
        bar = ttk.Progressbar(c, mode="indeterminate")
        bar.pack(fill="x", pady=10)
        bar.start(15)
        self.wait_var = tk.StringVar()
        ttk.Label(c, textvariable=self.wait_var, style="WizHint.TLabel").pack(anchor="w")
        self._nav(back=self._cancel_scan)
        self.back_btn.config(text="Abbrechen")
        self._cancel.clear()
        self._busy = True
        threading.Thread(target=self._scan_worker, args=(self.source,), daemon=True).start()

    def _cancel_scan(self):
        self._cancel.set()

    def _scan_worker(self, source):
        def progress(msg):
            if self._cancel.is_set():
                raise _Cancelled()
            self._queue.put(("WAIT", msg))

        try:
            self._queue.put(("SCANNED", scan_source(source, progress_cb=progress)))
        except _Cancelled:
            self._queue.put(("SCAN_ABORT", None))
        except Exception as exc:  # noqa: BLE001
            self._queue.put(("SCAN_ERROR", str(exc)))

    def _on_scanned(self, result):
        self.scan_result = result
        self.volumes = [s for s in result.series if s.kind == KIND_VOLUME]
        self.checked = {}
        self.patient_vars = {}
        self._show_volumes()

    # ================================================== Schritt 2: Aufnahme
    def _show_volumes(self):
        self.back_btn.config(text="‹  Zurück")
        if not self.volumes:
            c = self._page(1, "Hier wurde leider keine 3D-Aufnahme gefunden",
                           "Auf diesem Datenträger liegt keine lesbare DVT-Aufnahme.")
            ttk.Label(c, style="WizText.TLabel", wraplength=880, justify="left", text=(
                "Das können Sie tun:\n\n"
                "•  Prüfen, ob der richtige Stick eingesteckt ist, und es noch einmal versuchen.\n\n"
                "•  Liegt auf dem Stick eine ZIP-Datei? Diese muss erst entpackt werden "
                "(Rechtsklick → „Alle extrahieren“). Danach den entpackten Ordner auswählen.\n\n"
                "•  Wenn es nicht klappt: Stick beiseitelegen und Felix Bescheid geben.")).pack(anchor="w")
            self._nav(back=self._show_source)
            return

        many = len(self.volumes) > 1
        c = self._page(1, "Es wurden mehrere Aufnahmen gefunden" if many else "Die Aufnahme wurde gefunden",
                       "Rechts sehen Sie eine Vorschau. Bewegen Sie den Regler unter dem Bild: "
                       "Wenn Zähne und Kiefer zu erkennen sind, ist alles in Ordnung.")
        c.columnconfigure(0, weight=1)
        left = ttk.Frame(c)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 24))
        self.preview = PreviewPanel(c, size=340)
        self.preview.grid(row=0, column=1, sticky="n")

        if many:
            ttk.Label(left, style="WizText.TLabel", wraplength=470, justify="left",
                      text="Im Zweifel einfach alle Häkchen gesetzt lassen.").pack(anchor="w", pady=(0, 8))
        self.show_var = tk.IntVar(value=0)
        for i, series in enumerate(self.volumes):
            self.checked.setdefault(series.key, tk.BooleanVar(value=True))
            row = ttk.Frame(left)
            row.pack(fill="x", pady=4)
            date = self._format_date(series.patient.study_date)
            label = f"{series.patient.display_name}" + (f", vom {date}" if date else "") \
                + f"  ({series.num_output} Schichten)"
            if many:
                ttk.Checkbutton(row, text=label, variable=self.checked[series.key], style="Wiz.TCheckbutton",
                                command=self._volumes_changed).pack(side="left")
                ttk.Radiobutton(row, text="ansehen", value=i, variable=self.show_var,
                                command=self._preview_selected).pack(side="right")
            else:
                ttk.Label(row, text=label, style="WizText.TLabel").pack(side="left")
        self.volume_notes = ttk.Frame(left)
        self.volume_notes.pack(fill="x", pady=(14, 0))
        self._nav(back=self._show_source, nxt=self._show_patient)
        self._preview_selected()
        self._volumes_changed()

    def _selected(self) -> list:
        return [s for s in self.volumes if self.checked[s.key].get()]

    def _volumes_changed(self):
        self.next_btn.config(state="normal" if self._selected() else "disabled")

    def _preview_selected(self):
        series = self.volumes[self.show_var.get()]
        for child in self.volume_notes.winfo_children():
            child.destroy()
        if series.num_missing:
            ttk.Label(self.volume_notes, style="WizWarn.TLabel", wraplength=470, justify="left",
                      text=f"Hinweis: Bei dieser Aufnahme fehlen {series.num_missing} Schicht(en).").pack(anchor="w")
            ttk.Label(self.volume_notes, style="WizText.TLabel", wraplength=470, justify="left",
                      text="Das ist kein Hindernis: Die fehlenden Schichten werden automatisch durch "
                           "schwarze Bilder ersetzt. Bitte dem Behandler Bescheid geben, dass an "
                           "diesen Stellen nichts zu sehen ist.").pack(anchor="w", pady=(4, 0))
        else:
            ttk.Label(self.volume_notes, style="WizOk.TLabel",
                      text="✓  Die Aufnahme ist vollständig.").pack(anchor="w")
        if series.plan is not None and not series.plan.spacing_known:
            ttk.Label(self.volume_notes, style="WizWarn.TLabel", wraplength=470, justify="left",
                      text="Achtung: In dieser Aufnahme fehlt die Größenangabe. Längenmessungen "
                           "sind nicht verlässlich – bitte dem Behandler mitteilen.").pack(anchor="w", pady=(8, 0))
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            self.preview.set_series(series)
        finally:
            self.config(cursor="")

    # =================================================== Schritt 3: Patient
    def _show_patient(self):
        c = self._page(2, "Für welchen Patienten ist die Aufnahme?",
                       "Bitte genau so eintragen, wie der Patient in Sidexis angelegt ist. "
                       "Die Felder sind mit den Angaben vom Stick vorausgefüllt – bitte prüfen und "
                       "bei Bedarf ändern.")
        first = self._selected()[0].patient
        if not self.patient_vars:
            self.patient_vars = {
                "last_name": tk.StringVar(value=first.last_name),
                "first_name": tk.StringVar(value=first.first_name),
                "birth_date": tk.StringVar(value=self._format_date(first.birth_date)),
            }
        form = ttk.Frame(c)
        form.pack(anchor="w")
        for r, (name, label, hint) in enumerate((
                ("last_name", "Nachname", ""),
                ("first_name", "Vorname", ""),
                ("birth_date", "Geburtsdatum", "Tag.Monat.Jahr, zum Beispiel 24.12.1985"))):
            ttk.Label(form, text=label, style="WizText.TLabel").grid(row=r, column=0, sticky="w", pady=8, padx=(0, 16))
            entry = ttk.Entry(form, textvariable=self.patient_vars[name], font=("", 14), width=26)
            entry.grid(row=r, column=1, sticky="w", pady=8)
            if hint:
                ttk.Label(form, text=hint, style="WizHint.TLabel").grid(row=r, column=2, sticky="w", padx=12)
            if r == 0:
                entry.focus_set()
        self.patient_error = ttk.Label(c, style="WizWarn.TLabel", wraplength=880, justify="left")
        self.patient_error.pack(anchor="w", pady=(14, 0))
        self._nav(back=self._show_volumes, nxt=self._patient_next)

    def _patient_next(self):
        last = self.patient_vars["last_name"].get().strip()
        first = self.patient_vars["first_name"].get().strip()
        birth = self._parse_date(self.patient_vars["birth_date"].get())
        if not last:
            self.patient_error.config(text="Bitte den Nachnamen eintragen.")
            return
        for series in self._selected():
            p = series.patient
            p.last_name, p.first_name, p.birth_date = last, first, birth
        if validate_patient(self._selected()[0].patient):
            self.patient_error.config(
                text="Das Geburtsdatum ist so nicht gültig. Bitte in der Form 24.12.1985 eintragen "
                     "(oder das Feld leer lassen).")
            return
        self._show_destination()

    # ================================================ Schritt 4: Speicherort
    def _show_destination(self):
        c = self._page(3, "Wo soll die fertige Aufnahme gespeichert werden?",
                       "Wenn Sie unsicher sind: einfach die erste Möglichkeit ausgewählt lassen "
                       "und auf „Weiter“ klicken.")
        is_default = self.output_base == self.default_base
        self.dest_choice = tk.StringVar(value="default" if is_default else "custom")
        ttk.Radiobutton(c, text="Im üblichen Ordner (empfohlen)", value="default", variable=self.dest_choice,
                        style="Wiz.TRadiobutton", command=self._dest_changed).pack(anchor="w", pady=(0, 2))
        ttk.Label(c, text=str(self.default_base), style="WizHint.TLabel").pack(anchor="w", padx=28)
        ttk.Radiobutton(c, text="In einem anderen Ordner", value="custom", variable=self.dest_choice,
                        style="Wiz.TRadiobutton", command=self._dest_changed).pack(anchor="w", pady=(18, 2))
        row = ttk.Frame(c)
        row.pack(anchor="w", padx=28, fill="x")
        self.custom_dest_var = tk.StringVar(value="" if is_default else str(self.output_base))
        self.dest_btn = ttk.Button(row, text="Ordner auswählen …", style="Wiz.TButton", command=self._pick_dest)
        self.dest_btn.pack(side="left", padx=(0, 12))
        ttk.Label(row, textvariable=self.custom_dest_var, style="WizHint.TLabel").pack(side="left")
        ttk.Label(c, style="WizHint.TLabel", wraplength=880, justify="left",
                  text="Dort wird automatisch ein neuer Unterordner mit dem Namen des Patienten angelegt. "
                       "Der USB-Stick selbst wird nicht verändert.").pack(anchor="w", pady=(24, 0))
        self._nav(back=self._show_patient, nxt=self._show_summary)
        self._dest_changed()

    def _dest_changed(self):
        custom = self.dest_choice.get() == "custom"
        self.dest_btn.config(state="normal" if custom else "disabled")
        self.output_base = Path(self.custom_dest_var.get()) if custom and self.custom_dest_var.get() \
            else self.default_base
        self.next_btn.config(state="normal" if not custom or self.custom_dest_var.get() else "disabled")

    def _pick_dest(self):
        path = filedialog.askdirectory(parent=self, title="Ordner zum Speichern auswählen")
        if path:
            self.custom_dest_var.set(path)
            self._dest_changed()

    # ============================================= Schritt 5: Fertigstellen
    def _show_summary(self):
        selected = self._selected()
        p = selected[0].patient
        c = self._page(4, "Stimmt alles?", "Bitte kurz prüfen. Mit „Zurück“ können Sie noch etwas ändern.")
        grid = ttk.Frame(c)
        grid.pack(anchor="w")
        missing = sum(s.num_missing for s in selected)
        rows = [
            ("Aufnahme von", self.source_label),
            ("Patient", p.display_name),
            ("Geburtsdatum", self._format_date(p.birth_date) or "(nicht angegeben)"),
            ("Aufnahmen", f"{len(selected)}  ({sum(s.num_output for s in selected)} Schichten)"),
            ("Speicherort", str(self.output_base)),
        ]
        if missing:
            rows.insert(4, ("Fehlende Schichten", f"{missing} – werden schwarz ersetzt"))
        for r, (label, value) in enumerate(rows):
            ttk.Label(grid, text=label + ":", style="WizHint.TLabel", font=("", 13)).grid(
                row=r, column=0, sticky="nw", pady=6, padx=(0, 20))
            ttk.Label(grid, text=value, style="WizText.TLabel", wraplength=640, justify="left").grid(
                row=r, column=1, sticky="w", pady=6)
        self._nav(back=self._show_destination, nxt=self._start_convert, next_text="Jetzt fertigstellen  ✓")

    def _start_convert(self):
        selected = self._selected()
        out_dir = self.output_base / self._folder_name(selected[0].patient)
        c = self._page(4, "Die Aufnahme wird vorbereitet …",
                       "Bitte warten und den USB-Stick noch nicht herausziehen.")
        self.conv_bar = ttk.Progressbar(c, mode="determinate")
        self.conv_bar.pack(fill="x", pady=10)
        self.wait_var = tk.StringVar()
        ttk.Label(c, textvariable=self.wait_var, style="WizHint.TLabel").pack(anchor="w")
        self._nav()
        self._cancel.clear()
        self._busy = True
        threading.Thread(target=self._convert_worker, args=(selected, out_dir), daemon=True).start()

    def _convert_worker(self, selected, out_dir: Path):
        def progress(done, total):
            if self._cancel.is_set():
                raise _Cancelled()
            self._queue.put(("PROGRESS", (done, total)))

        try:
            self._queue.put(("CONVERTED", convert_series_list(selected, out_dir, progress_cb=progress)))
        except _Cancelled:
            self._cleanup(out_dir)
        except Exception as exc:  # noqa: BLE001
            self._cleanup(out_dir)
            self._queue.put(("CONVERT_ERROR", str(exc)))

    @staticmethod
    def _cleanup(out_dir: Path):
        for path in (out_dir, out_dir.parent / (out_dir.name + FLAT_SUFFIX)):
            shutil.rmtree(path, ignore_errors=True)

    def _show_done(self, result):
        self.result = result
        ok = result.verified and result.series_converted > 0
        c = self._page(4, "Geschafft! Die Aufnahme ist bereit für Sidexis." if ok
                       else "Die Aufnahme wurde gespeichert – bitte Hinweise beachten")
        black = result.black_missing + result.black_damaged
        if black or result.partially_damaged:
            ttk.Label(c, style="WizWarn.TLabel", wraplength=880, justify="left",
                      text=f"Hinweis für den Behandler: {black + result.partially_damaged} Schicht(en) "
                           "fehlten oder waren beschädigt und wurden schwarz ersetzt.").pack(anchor="w", pady=(0, 10))
        for line in result.problems:
            ttk.Label(c, style="WizWarn.TLabel", wraplength=880, justify="left",
                      text=f"Hinweis: {line}").pack(anchor="w", pady=(0, 6))
        ttk.Label(c, text="Die Aufnahme liegt jetzt in diesem Ordner:", style="WizText.TLabel").pack(anchor="w")
        row = ttk.Frame(c)
        row.pack(fill="x", pady=(6, 16))
        self.path_var = tk.StringVar(value=str(result.output_dir))   # Referenz halten, sonst leeres Feld
        ttk.Entry(row, textvariable=self.path_var, state="readonly", font=("", 12)).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Pfad kopieren", style="Wiz.TButton", command=self._copy_path).pack(side="left", padx=8)
        ttk.Button(row, text="Ordner öffnen", style="Wiz.TButton",
                   command=lambda: open_in_file_manager(result.output_dir)).pack(side="left")
        ttk.Label(c, text="So geht es in Sidexis weiter:", style="WizText.TLabel",
                  font=("", 13, "bold")).pack(anchor="w")
        ttk.Label(c, style="WizText.TLabel", wraplength=880, justify="left", text=(
            "1.  Sidexis öffnen und den Patienten auswählen.\n"
            "2.  Den DICOM-Import aufrufen.\n"
            "3.  Den oben genannten Ordner auswählen (oder die Datei „DICOMDIR“ darin).\n"
            "4.  Import bestätigen – fertig.\n\n"
            "Der USB-Stick kann jetzt herausgezogen werden.")).pack(anchor="w", pady=(6, 0))
        self._nav(back=self._restart, nxt=self._close, next_text="Schließen")
        self.back_btn.config(text="Noch eine Aufnahme")

    def _copy_path(self):
        self.clipboard_clear()
        self.clipboard_append(str(self.result.output_dir))

    def _restart(self):
        self.back_btn.config(text="‹  Zurück")
        self.source = None
        self.custom_folder = None
        self.scan_result = None
        self._show_source()

    # =============================================================== Ablauf
    def _handle(self, kind, payload):
        if kind == "WAIT":
            if hasattr(self, "wait_var"):
                self.wait_var.set(payload)
        elif kind == "PROGRESS":
            done, total = payload
            try:   # verspätete Meldungen nach einem Seitenwechsel ignorieren
                self.conv_bar.config(maximum=max(total, 1), value=done)
                self.wait_var.set(f"Schicht {done} von {total}")
            except (AttributeError, tk.TclError):
                pass
        elif kind == "SCANNED":
            self._busy = False
            self._on_scanned(payload)
        elif kind == "SCAN_ABORT":
            self._busy = False
            self.back_btn.config(text="‹  Zurück")
            self._show_source()
        elif kind == "SCAN_ERROR":
            self._busy = False
            self.back_btn.config(text="‹  Zurück")
            messagebox.showerror("Das hat nicht geklappt", "Der Datenträger konnte nicht gelesen werden.\n\n"
                                 f"({payload})", parent=self)
            self._show_source()
        elif kind == "CONVERTED":
            self._busy = False
            self._show_done(payload)
        elif kind == "CONVERT_ERROR":
            self._busy = False
            messagebox.showerror("Das hat nicht geklappt",
                                 "Die Aufnahme konnte nicht gespeichert werden.\n\n"
                                 f"({payload})\n\nBitte Felix Bescheid geben.", parent=self)
            self._show_summary()

    def _poll(self):
        try:
            while True:
                self._handle(*self._queue.get_nowait())
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._poll)

    def _close(self):
        if self._busy and not messagebox.askyesno("Wirklich abbrechen?",
                                                  "Der Vorgang läuft noch. Wirklich abbrechen?", parent=self):
            return
        self._cancel.set()
        self.destroy()
