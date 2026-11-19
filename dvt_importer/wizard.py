"""„Felix ist nicht da“-Modus: führt Schritt für Schritt mit einfachen Fragen durch
den gesamten Ablauf - ohne Fachbegriffe, immer nur eine Entscheidung pro Seite.
"""
from __future__ import annotations

import queue
import sys
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .converter import FLAT_SUFFIX, convert_series_list, validate_patient
from .drives import cached_removable_drives as list_removable_drives
from .drives import open_in_file_manager
from .preview import PreviewPanel
from .scanner import KIND_VOLUME, scan_source

MODE_NAME = "Felix ist nicht da-Modus"
ACCENT = "#e8590c"
STEPS = ("Stick wählen", "Aufnahme ansehen", "Patient", "Speicherort", "Fertigstellen")


class _Cancelled(Exception):
    pass


class SeriesCardList(ttk.Frame):
    """Liste anklickbarer Karten, eine pro Aufnahme.

    Ein Klick auf die Karte wählt sie aus (farbig hervorgehoben, Vorschau rechts).
    Das Kästchen links legt fest, ob die Aufnahme übernommen wird. Bei vielen
    Aufnahmen wird die Liste scrollbar.
    """

    BG = "#ffffff"
    BG_HOVER = "#f4f5f7"
    BG_SELECTED = "#fff4e6"
    BORDER = "#d0d4da"
    TEXT = "#1f2328"
    SUBTEXT = "#5c636a"
    OK = "#2b8a3e"
    WARN = "#c92a2a"
    MAX_VISIBLE = 3

    def __init__(self, parent, series_list, checked: dict, *, with_checkbox: bool, on_select, on_toggle):
        super().__init__(parent)
        self.series_list = series_list
        self.checked = checked
        self.with_checkbox = with_checkbox
        self.on_select = on_select
        self.on_toggle = on_toggle
        self.index = -1
        self.cards: list = []

        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0,
                                background=ttk.Style(self).lookup("TFrame", "background") or self.BG)
        self.inner = tk.Frame(self.canvas, background=self.canvas.cget("background"))
        self._window = self.canvas.create_window(0, 0, anchor="nw", window=self.inner)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", self._on_inner_resize)
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._window, width=e.width))

        for i, series in enumerate(series_list):
            self.cards.append(self._make_card(i, series))

    # ----------------------------------------------------------- Aufbau
    def _make_card(self, index: int, series) -> dict:
        from .gui import format_date

        card = tk.Frame(self.inner, background=self.BG, highlightthickness=2,
                        highlightbackground=self.BORDER, highlightcolor=self.BORDER, cursor="hand2")
        card.pack(fill="x", pady=(0, 6), padx=(0, 4))
        widgets = [card]

        box = None
        if self.with_checkbox:
            box = tk.Canvas(card, width=26, height=26, highlightthickness=0, background=self.BG, cursor="hand2")
            box.pack(side="left", padx=(12, 4), pady=8)
            box.bind("<Button-1>", lambda _e, i=index: self._toggle(i))
            widgets.append(box)

        text = tk.Frame(card, background=self.BG)
        text.pack(side="left", fill="x", expand=True, padx=(12 if box is None else 6, 12), pady=7)
        widgets.append(text)
        title = tk.Label(text, text=series.patient.display_name, background=self.BG, foreground=self.TEXT,
                         font=("", 14, "bold"), anchor="w")
        title.pack(fill="x")
        date = format_date(series.patient.study_date)
        details = "  ·  ".join(x for x in (
            f"Aufnahme vom {date}" if date else "",
            f"{series.num_output} Schichten",
            " ".join(x for x in (series.manufacturer, series.model) if x),
        ) if x)
        sub = tk.Label(text, text=details, background=self.BG, foreground=self.SUBTEXT, font=("", 11), anchor="w")
        sub.pack(fill="x")
        if series.num_missing:
            status_text, status_color = f"⚠  {series.num_missing} Schicht(en) fehlen – werden schwarz ergänzt", self.WARN
        else:
            status_text, status_color = "✓  vollständig", self.OK
        status = tk.Label(text, text=status_text, background=self.BG, foreground=status_color,
                          font=("", 11, "bold"), anchor="w")
        status.pack(fill="x", pady=(2, 0))
        widgets += [title, sub, status]

        for w in widgets:
            if w is not box:
                w.bind("<Button-1>", lambda _e, i=index: self.select(i))
            w.bind("<Enter>", lambda _e, i=index: self._hover(i, True))
            w.bind("<Leave>", lambda _e, i=index: self._hover(i, False))
            w.bind("<MouseWheel>", self._on_wheel)
            w.bind("<Button-4>", lambda _e: self.canvas.yview_scroll(-1, "units"))
            w.bind("<Button-5>", lambda _e: self.canvas.yview_scroll(1, "units"))
        entry = {"frame": card, "box": box, "widgets": widgets, "hover": False}
        self._draw_box(entry, self.checked[series.key].get())
        return entry

    def _on_inner_resize(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        cards = [c["frame"] for c in self.cards]
        if not cards:
            return
        visible = cards[: self.MAX_VISIBLE]
        height = sum(c.winfo_reqheight() + 6 for c in visible)
        self.canvas.configure(height=height)
        needs_scroll = len(cards) > self.MAX_VISIBLE
        if needs_scroll and not self.scrollbar.winfo_ismapped():
            self.scrollbar.pack(side="right", fill="y")
        elif not needs_scroll and self.scrollbar.winfo_ismapped():
            self.scrollbar.pack_forget()

    # ------------------------------------------------------- Verhalten
    def select(self, index: int) -> None:
        if not 0 <= index < len(self.cards):
            return
        changed = index != self.index
        self.index = index
        for i in range(len(self.cards)):
            self._paint(i)
        self._scroll_into_view(index)
        if changed:
            self.on_select(self.series_list[index])

    def move(self, delta: int) -> None:
        self.select(min(max(self.index + delta, 0), len(self.cards) - 1))

    @property
    def selected_series(self):
        return self.series_list[self.index] if self.index >= 0 else None

    def _toggle(self, index: int) -> None:
        var = self.checked[self.series_list[index].key]
        var.set(not var.get())
        self._draw_box(self.cards[index], var.get())
        self.on_toggle()
        self.select(index)

    def _hover(self, index: int, inside: bool) -> None:
        self.cards[index]["hover"] = inside
        self._paint(index)

    def _paint(self, index: int) -> None:
        entry = self.cards[index]
        selected = index == self.index
        bg = self.BG_SELECTED if selected else (self.BG_HOVER if entry["hover"] else self.BG)
        border = ACCENT if selected else self.BORDER
        entry["frame"].configure(highlightbackground=border, highlightcolor=border)
        for w in entry["widgets"]:
            w.configure(background=bg)

    def _draw_box(self, entry: dict, on: bool) -> None:
        box = entry["box"]
        if box is None:
            return
        box.delete("all")
        if on:
            box.create_rectangle(3, 3, 23, 23, fill=ACCENT, outline=ACCENT, width=2)
            box.create_line(7, 13, 11, 18, 19, 8, fill="white", width=3, capstyle="round", joinstyle="round")
        else:
            box.create_rectangle(3, 3, 23, 23, fill="white", outline="#8a9099", width=2)

    def _scroll_into_view(self, index: int) -> None:
        if not self.scrollbar.winfo_ismapped():
            return
        self.update_idletasks()
        frame = self.cards[index]["frame"]
        total = max(self.inner.winfo_height(), 1)
        top, bottom = frame.winfo_y(), frame.winfo_y() + frame.winfo_height()
        view_top, view_bottom = (f * total for f in self.canvas.yview())
        if top < view_top:
            self.canvas.yview_moveto(top / total)
        elif bottom > view_bottom:
            self.canvas.yview_moveto((bottom - (view_bottom - view_top)) / total)

    def _on_wheel(self, event):
        if self.scrollbar.winfo_ismapped():
            step = -1 if event.delta > 0 else 1
            self.canvas.yview_scroll(step, "units")


class WizardWindow(tk.Toplevel):
    def __init__(self, parent, output_base: Path):
        super().__init__(parent)
        from .gui import format_date, parse_date, unique_output_dir  # hier wegen Kreisimport

        self._format_date, self._parse_date, self._unique_dir = format_date, parse_date, unique_output_dir
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
        self.unbind("<Up>")
        self.unbind("<Down>")
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
                       "Klicken Sie links eine Aufnahme an – rechts erscheint die Vorschau. Bewegen Sie den "
                       "Regler unter dem Bild: Wenn Zähne und Kiefer zu erkennen sind, ist alles in Ordnung."
                       if many else
                       "Rechts sehen Sie eine Vorschau. Bewegen Sie den Regler unter dem Bild: "
                       "Wenn Zähne und Kiefer zu erkennen sind, ist alles in Ordnung.")
        c.columnconfigure(0, weight=1)
        c.rowconfigure(0, weight=1)
        left = ttk.Frame(c)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 24))
        right = ttk.Frame(c)
        right.grid(row=0, column=1, sticky="n")
        self.preview = PreviewPanel(right, size=340)
        self.preview.pack()
        ttk.Button(right, text="Groß ansehen (Notfall-Viewer) …", style="Wiz.TButton",
                   command=self._open_viewer_selected).pack(fill="x", pady=(8, 0))

        if many:
            ttk.Label(left, style="WizHint.TLabel", wraplength=470, justify="left",
                      text="Aufnahmen mit Häkchen werden übernommen. Im Zweifel alle Häkchen gesetzt lassen."
                      ).pack(anchor="w", pady=(0, 8))
        for series in self.volumes:
            self.checked.setdefault(series.key, tk.BooleanVar(value=True))
        self.cards = SeriesCardList(left, self.volumes, self.checked, with_checkbox=many,
                                    on_select=self._preview_selected, on_toggle=self._volumes_changed)
        self.cards.pack(fill="x")
        self.volume_notes = ttk.Frame(left)
        self.volume_notes.pack(fill="x", pady=(12, 0))
        self._nav(back=self._show_source, nxt=self._show_patient)
        self.bind("<Up>", lambda _e: self.cards.move(-1))
        self.bind("<Down>", lambda _e: self.cards.move(1))
        self.cards.select(0)
        self._volumes_changed()

    def _selected(self) -> list:
        return [s for s in self.volumes if self.checked[s.key].get()]

    def _volumes_changed(self):
        self.next_btn.config(state="normal" if self._selected() else "disabled")

    def _preview_selected(self, series):
        for child in self.volume_notes.winfo_children():
            child.destroy()
        if series.num_missing:
            ttk.Label(self.volume_notes, style="WizText.TLabel", wraplength=520, justify="left",
                      text="Fehlende Schichten sind kein Hindernis – sie werden automatisch schwarz ergänzt. "
                           "Bitte dem Behandler Bescheid geben, dass dort nichts zu sehen ist."
                      ).pack(anchor="w")
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
        patient = self._selected()[0].patient
        c = self._page(3, "Wo soll die fertige Aufnahme gespeichert werden?",
                       "Am besten einfach so lassen und auf „Weiter“ klicken.")
        is_default = self.output_base == self.default_base
        self.dest_choice = tk.StringVar(value="default" if is_default else "custom")
        ttk.Radiobutton(c, text="Auf dem Desktop, in einem Ordner mit dem Namen des Patienten (empfohlen)",
                        value="default", variable=self.dest_choice, style="Wiz.TRadiobutton",
                        command=self._dest_changed).pack(anchor="w", pady=(0, 4))
        folder = self._unique_dir(self.default_base, patient)
        tk.Label(c, text=folder.name, font=("", 15, "bold"), foreground=ACCENT,
                 background=self.cget("background")).pack(anchor="w", padx=28)
        ttk.Label(c, text=str(folder), style="WizHint.TLabel").pack(anchor="w", padx=28, pady=(2, 0))
        ttk.Radiobutton(c, text="In einem anderen Ordner", value="custom", variable=self.dest_choice,
                        style="Wiz.TRadiobutton", command=self._dest_changed).pack(anchor="w", pady=(26, 4))
        row = ttk.Frame(c)
        row.pack(anchor="w", padx=28, fill="x")
        self.custom_dest_var = tk.StringVar(value="" if is_default else str(self.output_base))
        self.dest_btn = ttk.Button(row, text="Ordner auswählen …", style="Wiz.TButton", command=self._pick_dest)
        self.dest_btn.pack(side="left", padx=(0, 12))
        ttk.Label(row, textvariable=self.custom_dest_var, style="WizHint.TLabel").pack(side="left")
        ttk.Label(c, style="WizHint.TLabel", wraplength=880, justify="left",
                  text="Auch dort wird ein Ordner mit dem Namen des Patienten angelegt. "
                       "Der USB-Stick selbst wird nicht verändert.").pack(anchor="w", padx=28, pady=(8, 0))
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
            ("Speicherort", str(self._unique_dir(self.output_base, p))),
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
        out_dir = self._unique_dir(self.output_base, selected[0].patient)
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
        p = self._selected()[0].patient
        folder = Path(result.output_dir)
        on_desktop = folder.parent == self.default_base
        c = self._page(4, "Geschafft! Jetzt nur noch in Sidexis importieren." if ok
                       else "Die Aufnahme wurde gespeichert – bitte Hinweise beachten")
        black = result.black_missing + result.black_damaged
        if black or result.partially_damaged:
            ttk.Label(c, style="WizWarn.TLabel", wraplength=880, justify="left",
                      text=f"Hinweis für den Behandler: {black + result.partially_damaged} Schicht(en) "
                           "fehlten oder waren beschädigt und wurden schwarz ersetzt.").pack(anchor="w", pady=(0, 6))
        for line in result.problems:
            ttk.Label(c, style="WizWarn.TLabel", wraplength=880, justify="left",
                      text=f"Hinweis: {line}").pack(anchor="w", pady=(0, 6))

        row = ttk.Frame(c)
        row.pack(fill="x", pady=(0, 12))
        where = "auf dem Desktop" if on_desktop else "im Ordner"
        ttk.Label(row, text=f"Gespeichert {where}:", style="WizText.TLabel").pack(side="left")
        tk.Label(row, text=folder.name, font=("", 14, "bold"), foreground=ACCENT,
                 background=self.cget("background")).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Ordner zeigen", style="Wiz.TButton",
                   command=lambda: open_in_file_manager(folder)).pack(side="right")
        self.path_var = tk.StringVar(value=str(folder))   # für Tests / „Pfad kopieren“

        ttk.Label(c, text="So importieren Sie die Aufnahme in Sidexis 4:", style="WizText.TLabel",
                  font=("", 13, "bold")).pack(anchor="w", pady=(0, 6))
        steps = [
            f"Sidexis 4 öffnen und den Patienten {p.display_name} auswählen.",
            "Oben in den Bereich „Aufnahme“ wechseln.",
            "Auf „Import“ klicken.",
            ("Im Auswahlfenster links auf „Desktop“ (Mac: „Schreibtisch“) klicken, "
             if on_desktop else "Im Auswahlfenster zum oben genannten Speicherort gehen, ")
            + f"den Ordner „{folder.name}“ öffnen und die Datei „DICOMDIR“ auswählen, dann „Öffnen“.",
            "Sidexis zeigt die Aufnahme an: prüfen, dass sie dem richtigen Patienten zugeordnet wird, "
            "und den Import bestätigen.",
            "Die Aufnahme erscheint beim Patienten – alles okay, es hat geklappt!",
        ]
        steps_frame = ttk.Frame(c)
        steps_frame.pack(fill="x")
        steps_frame.columnconfigure(1, weight=1)
        for i, text in enumerate(steps):
            last = i == len(steps) - 1
            tk.Label(steps_frame, text="✓" if last else str(i + 1), width=2, font=("", 12, "bold"),
                     foreground="white", background="#2b8a3e" if last else ACCENT).grid(
                row=i, column=0, sticky="nw", pady=3, padx=(0, 12))
            ttk.Label(steps_frame, text=text, wraplength=780, justify="left",
                      style="WizOk.TLabel" if last else "WizText.TLabel").grid(row=i, column=1, sticky="w", pady=3)
        if sys.platform == "darwin":
            ttk.Label(c, style="WizHint.TLabel", wraplength=880, justify="left",
                      text="Sidexis läuft nur unter Windows: Den Ordner per USB-Stick oder Netzlaufwerk zum "
                           "Sidexis-PC bringen und dort auf den Desktop legen.").pack(anchor="w", pady=(8, 0))
        help_row = ttk.Frame(c)
        help_row.pack(anchor="w", pady=(10, 0))
        ttk.Button(help_row, text="Hat nicht geklappt?", command=self._show_import_help).pack(side="left")
        ttk.Button(help_row, text="Aufnahme im Notfall-Viewer ansehen …",
                   command=lambda: self._open_viewer_folder(folder)).pack(side="left", padx=(8, 0))
        self._nav(back=self._restart, nxt=self._finish_ok, next_text="✓  Hat geklappt – fertig")
        self.back_btn.config(text="Noch eine Aufnahme")

    def _finish_ok(self):
        self._close()

    def _show_import_help(self):
        messagebox.showinfo("Wenn der Import nicht klappt", (
            "• Sidexis meldet, die Aufnahme sei schon vorhanden:\n"
            "   Im Import-Fenster die Option zum Import von Duplikaten einschalten und erneut versuchen.\n\n"
            "• Im Auswahlfenster ist keine Datei „DICOMDIR“ zu sehen:\n"
            "   Prüfen, ob wirklich der Ordner mit dem Patientennamen geöffnet ist. "
            "Notfalls statt der Datei den ganzen Ordner auswählen.\n\n"
            "• Die Aufnahme landet beim falschen Patienten:\n"
            "   Nicht weiterarbeiten und Felix Bescheid geben.\n\n"
            "• Sonst: Den Ordner auf dem Desktop liegen lassen, den USB-Stick aufbewahren "
            "und Felix Bescheid geben – mit dem Wortlaut der Fehlermeldung von Sidexis.\n\n"
            "Bis dahin kann der Behandler die Aufnahme im Notfall-Viewer ansehen "
            "(Knopf „Aufnahme im Notfall-Viewer ansehen“)."), parent=self)

    def _open_viewer_selected(self):
        from .viewer import open_viewer

        if self.cards.selected_series is not None:
            open_viewer(self, series=self.cards.selected_series)

    def _open_viewer_folder(self, folder):
        from .viewer import open_viewer

        open_viewer(self, folder=Path(folder))

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
