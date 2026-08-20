"""Grafische Benutzeroberflaeche (Tkinter) fuer den DVT-Sidexis-Importer.

Ablauf fuer die Anwenderin/den Anwender in der Praxis:
  1. Fremden USB-Stick (oder Ordner mit dem DVT-Export) auswaehlen und scannen.
  2. Gefundene Serien pruefen/auswaehlen (Warnungen werden angezeigt).
  3. Zielordner waehlen und konvertieren.
  4. Den erzeugten Zielordner in Sidexis ueber "Datei > Import > DICOM" importieren.
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .converter import convert_series_list
from .scanner import scan_source

CHECK_ON = "☑"
CHECK_OFF = "☐"


class DvtImporterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"DVT-Sidexis-Importer v{__version__}")
        self.geometry("980x680")
        self.minsize(820, 560)

        self.source_dir: Path | None = None
        self.dest_dir: Path | None = None
        self.scan_result = None
        self.selected_keys: set[str] = set()
        self.row_id_to_series: dict[str, object] = {}

        self._log_queue: "queue.Queue[str]" = queue.Queue()
        self._worker_thread: threading.Thread | None = None

        self._build_widgets()
        self.after(100, self._poll_log_queue)

    # ------------------------------------------------------------------ UI
    def _build_widgets(self):
        pad = {"padx": 8, "pady": 6}

        # --- Schritt 1: Quelle ---
        frame1 = ttk.LabelFrame(self, text="1. Fremdes DVT auswaehlen (USB-Stick / Ordner)")
        frame1.pack(fill="x", **pad)

        self.source_label = ttk.Label(frame1, text="Kein Ordner ausgewaehlt", foreground="#555")
        self.source_label.pack(side="left", padx=8, pady=8, fill="x", expand=True)

        ttk.Button(frame1, text="Durchsuchen ...", command=self._choose_source).pack(side="right", padx=8, pady=8)
        self.scan_btn = ttk.Button(frame1, text="Scannen", command=self._start_scan, state="disabled")
        self.scan_btn.pack(side="right", padx=8, pady=8)

        # --- Schritt 2: Ergebnisliste ---
        frame2 = ttk.LabelFrame(self, text="2. Gefundene DVT-Serien (anklicken zum Auswaehlen)")
        frame2.pack(fill="both", expand=True, **pad)

        columns = ("check", "patient", "modality", "descr", "images", "warnings")
        self.tree = ttk.Treeview(frame2, columns=columns, show="headings", selectmode="none", height=10)
        self.tree.heading("check", text="")
        self.tree.heading("patient", text="Patient (ID)")
        self.tree.heading("modality", text="Modalitaet")
        self.tree.heading("descr", text="Beschreibung")
        self.tree.heading("images", text="Bilder")
        self.tree.heading("warnings", text="Hinweise")
        self.tree.column("check", width=32, anchor="center", stretch=False)
        self.tree.column("patient", width=220)
        self.tree.column("modality", width=80, anchor="center")
        self.tree.column("descr", width=180)
        self.tree.column("images", width=70, anchor="center")
        self.tree.column("warnings", width=340)
        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        self.tree.bind("<Button-1>", self._on_tree_click)

        scrollbar = ttk.Scrollbar(frame2, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="left", fill="y", pady=8)
        self.tree.configure(yscrollcommand=scrollbar.set)

        btns = ttk.Frame(frame2)
        btns.pack(side="left", fill="y", padx=8, pady=8)
        ttk.Button(btns, text="Alle auswaehlen", command=self._select_all).pack(fill="x", pady=2)
        ttk.Button(btns, text="Alle abwaehlen", command=self._select_none).pack(fill="x", pady=2)

        # --- Schritt 3: Ziel + Konvertieren ---
        frame3 = ttk.LabelFrame(self, text="3. Zielordner waehlen und konvertieren")
        frame3.pack(fill="x", **pad)

        self.dest_label = ttk.Label(frame3, text="Kein Zielordner ausgewaehlt", foreground="#555")
        self.dest_label.pack(side="left", padx=8, pady=8, fill="x", expand=True)

        ttk.Button(frame3, text="Zielordner waehlen ...", command=self._choose_dest).pack(side="right", padx=8, pady=8)
        self.convert_btn = ttk.Button(frame3, text="Konvertieren", command=self._start_convert, state="disabled")
        self.convert_btn.pack(side="right", padx=8, pady=8)

        # --- Fortschritt/Log ---
        frame4 = ttk.LabelFrame(self, text="Protokoll")
        frame4.pack(fill="both", expand=False, **pad)

        self.progress = ttk.Progressbar(frame4, mode="determinate")
        self.progress.pack(fill="x", padx=8, pady=(8, 4))

        self.log_text = tk.Text(frame4, height=8, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    # -------------------------------------------------------------- Events
    def _choose_source(self):
        path = filedialog.askdirectory(title="Fremden USB-Stick / Quellordner mit dem DVT auswaehlen")
        if not path:
            return
        self.source_dir = Path(path)
        self.source_label.config(text=str(self.source_dir), foreground="#000")
        self.scan_btn.config(state="normal")
        self.tree.delete(*self.tree.get_children())
        self.selected_keys.clear()
        self.scan_result = None
        self.convert_btn.config(state="disabled")

    def _choose_dest(self):
        path = filedialog.askdirectory(title="Zielordner fuer den Sidexis-Import waehlen")
        if not path:
            return
        self.dest_dir = Path(path)
        self.dest_label.config(text=str(self.dest_dir), foreground="#000")
        self._update_convert_btn_state()

    def _start_scan(self):
        if not self.source_dir:
            return
        self.scan_btn.config(state="disabled")
        self.tree.delete(*self.tree.get_children())
        self.selected_keys.clear()
        self._log(f"Durchsuche {self.source_dir} ...")
        self._worker_thread = threading.Thread(target=self._scan_worker, daemon=True)
        self._worker_thread.start()

    def _scan_worker(self):
        try:
            result = scan_source(self.source_dir, progress_cb=lambda m: self._log_queue.put(("STATUS", m)))
        except Exception as exc:  # noqa: BLE001
            self._log_queue.put(("ERROR", f"Fehler beim Scannen: {exc}"))
            self._log_queue.put(("SCAN_DONE", None))
            return
        self._log_queue.put(("SCAN_RESULT", result))
        self._log_queue.put(("SCAN_DONE", None))

    def _populate_tree(self, result):
        self.scan_result = result
        self.row_id_to_series.clear()
        if not result.series:
            self._log("Keine DICOM-Bilddaten gefunden. Bitte pruefen, ob der richtige Ordner/Stick gewaehlt wurde.")
            messagebox.showwarning(
                "Keine DICOM-Dateien gefunden",
                "Im gewaehlten Ordner wurden keine lesbaren DICOM-Bilddaten gefunden.\n"
                "Bitte pruefen Sie, ob der USB-Stick korrekt eingebunden ist und den DVT-Export enthaelt.",
            )
            return

        for series in result.series:
            row_id = self.tree.insert(
                "",
                "end",
                values=(
                    CHECK_OFF,
                    f"{series.patient_name} ({series.patient_id})",
                    series.modality,
                    series.series_description or "-",
                    series.num_slices,
                    "; ".join(series.warnings) if series.warnings else "keine",
                ),
            )
            self.row_id_to_series[row_id] = series

        self._log(
            f"{len(result.series)} Serie(n) gefunden "
            f"({result.total_files_seen} Dateien geprueft, {result.skipped_files} uebersprungen)."
        )
        self._select_all()

    def _on_tree_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.tree.identify_column(event.x)
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        if col == "#1":
            self._toggle_row(row_id)

    def _toggle_row(self, row_id):
        series = self.row_id_to_series.get(row_id)
        if series is None:
            return
        if series.key in self.selected_keys:
            self.selected_keys.discard(series.key)
            self.tree.set(row_id, "check", CHECK_OFF)
        else:
            self.selected_keys.add(series.key)
            self.tree.set(row_id, "check", CHECK_ON)
        self._update_convert_btn_state()

    def _select_all(self):
        for row_id, series in self.row_id_to_series.items():
            self.selected_keys.add(series.key)
            self.tree.set(row_id, "check", CHECK_ON)
        self._update_convert_btn_state()

    def _select_none(self):
        self.selected_keys.clear()
        for row_id in self.row_id_to_series:
            self.tree.set(row_id, "check", CHECK_OFF)
        self._update_convert_btn_state()

    def _update_convert_btn_state(self):
        ok = bool(self.selected_keys) and self.dest_dir is not None
        self.convert_btn.config(state="normal" if ok else "disabled")

    def _start_convert(self):
        if not self.selected_keys or not self.dest_dir:
            return
        selected_series = [s for s in self.scan_result.series if s.key in self.selected_keys]

        if any(self.dest_dir.iterdir()) if self.dest_dir.exists() else False:
            if not messagebox.askyesno(
                "Zielordner nicht leer",
                f"Der Zielordner '{self.dest_dir}' ist nicht leer.\n"
                "Vorhandene DICOM-Dateien/DICOMDIR koennten ueberschrieben werden.\n\nTrotzdem fortfahren?",
            ):
                return

        self.convert_btn.config(state="disabled")
        self.scan_btn.config(state="disabled")
        self.progress.config(value=0, maximum=100)
        self._log(f"Starte Konvertierung von {len(selected_series)} Serie(n) ...")

        self._worker_thread = threading.Thread(
            target=self._convert_worker, args=(selected_series,), daemon=True
        )
        self._worker_thread.start()

    def _convert_worker(self, selected_series):
        def log_cb(msg):
            self._log_queue.put(("STATUS", msg))

        def progress_cb(done, total):
            self._log_queue.put(("PROGRESS", (done, total)))

        try:
            result = convert_series_list(selected_series, self.dest_dir, log=log_cb, progress_cb=progress_cb)
        except Exception as exc:  # noqa: BLE001
            self._log_queue.put(("ERROR", f"Fehler bei der Konvertierung: {exc}"))
            self._log_queue.put(("CONVERT_DONE", None))
            return
        self._log_queue.put(("CONVERT_RESULT", result))
        self._log_queue.put(("CONVERT_DONE", None))

    # ------------------------------------------------------------- Logging
    def _log(self, message: str):
        self.log_text.config(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _poll_log_queue(self):
        try:
            while True:
                kind, payload = self._log_queue.get_nowait()
                if kind == "STATUS":
                    self._log(payload)
                elif kind == "ERROR":
                    self._log(payload)
                    messagebox.showerror("Fehler", payload)
                elif kind == "PROGRESS":
                    done, total = payload
                    self.progress.config(maximum=max(total, 1), value=done)
                elif kind == "SCAN_RESULT":
                    self._populate_tree(payload)
                elif kind == "SCAN_DONE":
                    self.scan_btn.config(state="normal")
                elif kind == "CONVERT_RESULT":
                    self._on_convert_done(payload)
                elif kind == "CONVERT_DONE":
                    self.convert_btn.config(state="normal")
                    self.scan_btn.config(state="normal")
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    def _on_convert_done(self, result):
        self._log(f"Konvertierung abgeschlossen: {result.series_converted} Serie(n), {result.images_converted} Bild(er).")
        for line in result.per_series_log:
            self._log(f"  - {line}")
        if result.decompression_failures:
            self._log(f"ACHTUNG: {len(result.decompression_failures)} Bild(er) konnten nicht dekomprimiert werden:")
            for line in result.decompression_failures:
                self._log(f"  - {line}")

        messagebox.showinfo(
            "Konvertierung abgeschlossen",
            f"Fertig!\n\n{result.series_converted} Serie(n) mit insgesamt {result.images_converted} Bildern "
            f"wurden nach:\n{result.output_dir}\n\nkonvertiert.\n\n"
            "Diesen Ordner in Sidexis ueber 'Datei > Import > DICOM' importieren "
            "(dort den Ordner bzw. die enthaltene DICOMDIR-Datei auswaehlen).",
        )


def main():
    app = DvtImporterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
