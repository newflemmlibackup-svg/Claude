"""Schritt-Editor: aufgenommene Ablaeufe durchsehen und nachbessern."""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from PIL import Image, ImageDraw, ImageTk

from . import APP_NAME
from .models import (
    KEY, ON_ERROR_ABORT, ON_ERROR_RETRY, ON_ERROR_SKIP, TEXT, WAIT, Macro, Step,
)

ERROR_LABELS = {
    ON_ERROR_ABORT: "Ablauf anhalten",
    ON_ERROR_SKIP: "Schritt ueberspringen",
    ON_ERROR_RETRY: "Nochmal versuchen, dann anhalten",
}
ERROR_BY_LABEL = {value: key for key, value in ERROR_LABELS.items()}
PREVIEW_MAX = (300, 210)


class StepEditor(tk.Toplevel):
    def __init__(self, parent: tk.Tk, app, slug: str):
        super().__init__(parent)
        self.app = app
        self.slug = slug
        self.macro: Macro = app.store.load(slug)
        self.current: Optional[int] = None
        self._preview_image = None
        self._loading = False

        self.title(f"Bearbeiten: {self.macro.name}")
        self.geometry("880x580")
        self.minsize(760, 480)
        self.transient(parent)
        self._build()
        self._fill_list()
        self.protocol("WM_DELETE_WINDOW", self.close)

    # ------------------------------------------------------------------
    def _build(self) -> None:
        header = ttk.Frame(self, padding=(12, 10))
        header.pack(fill=tk.X)
        ttk.Label(header, text="Name").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar(value=self.macro.name)
        ttk.Entry(header, textvariable=self.name_var, width=28).grid(row=0, column=1, sticky="w", padx=(6, 18))
        ttk.Label(header, text="Tempo").grid(row=0, column=2, sticky="w")
        self.speed_var = tk.StringVar(value=str(self.macro.speed))
        ttk.Entry(header, textvariable=self.speed_var, width=6).grid(row=0, column=3, sticky="w", padx=(6, 18))
        ttk.Label(header, text="Durchlaeufe").grid(row=0, column=4, sticky="w")
        self.repeat_var = tk.StringVar(value=str(self.macro.repeat))
        ttk.Entry(header, textvariable=self.repeat_var, width=6).grid(row=0, column=5, sticky="w", padx=(6, 18))
        ttk.Label(header, text="Kuerzel").grid(row=0, column=6, sticky="w")
        self.hotkey_var = tk.StringVar(value=self.macro.hotkey)
        ttk.Entry(header, textvariable=self.hotkey_var, width=14).grid(row=0, column=7, sticky="w", padx=(6, 0))

        body = ttk.Frame(self, padding=(12, 0))
        body.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(body)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(left, activestyle="dotbox", exportselection=False)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.listbox.yview)
        scrollbar.pack(side=tk.LEFT, fill=tk.Y)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        right = ttk.Frame(body, padding=(12, 0, 0, 0))
        right.pack(side=tk.LEFT, fill=tk.Y)
        self.preview = tk.Label(right, background="#e8e8e8", width=38, height=12,
                                text="Kein Bildausschnitt", relief=tk.SOLID, borderwidth=1)
        self.preview.pack()
        self.preview_hint = ttk.Label(right, text="", wraplength=PREVIEW_MAX[0], foreground="#555555")
        self.preview_hint.pack(anchor="w", pady=(4, 8))

        form = ttk.Frame(right)
        form.pack(fill=tk.X)
        ttk.Label(form, text="Pause davor (s)").grid(row=0, column=0, sticky="w", pady=2)
        self.delay_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.delay_var, width=10).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(form, text="Erkennungsschwelle").grid(row=1, column=0, sticky="w", pady=2)
        self.threshold_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.threshold_var, width=10).grid(row=1, column=1, sticky="w", padx=(8, 0))
        ttk.Label(form, text="Wartezeit (s)").grid(row=2, column=0, sticky="w", pady=2)
        self.timeout_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.timeout_var, width=10).grid(row=2, column=1, sticky="w", padx=(8, 0))
        ttk.Label(form, text="Wenn nicht gefunden").grid(row=3, column=0, sticky="w", pady=2)
        self.error_var = tk.StringVar(value=ERROR_LABELS[ON_ERROR_ABORT])
        ttk.Combobox(form, textvariable=self.error_var, values=list(ERROR_LABELS.values()),
                     state="readonly", width=30).grid(row=3, column=1, sticky="w", padx=(8, 0))
        ttk.Label(form, text="Text / Taste").grid(row=4, column=0, sticky="w", pady=2)
        self.text_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.text_var, width=30).grid(row=4, column=1, sticky="w", padx=(8, 0))
        ttk.Label(form, text="Notiz").grid(row=5, column=0, sticky="w", pady=2)
        self.note_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.note_var, width=30).grid(row=5, column=1, sticky="w", padx=(8, 0))
        ttk.Button(right, text="Aenderungen fuer diesen Schritt uebernehmen",
                   command=self._apply_fields).pack(fill=tk.X, pady=(10, 0))
        ttk.Button(right, text="Erkennung jetzt testen", command=self.test_recognition).pack(fill=tk.X, pady=(6, 0))
        self.test_result = ttk.Label(right, text="", wraplength=PREVIEW_MAX[0])
        self.test_result.pack(anchor="w", pady=(4, 0))

        tools = ttk.Frame(self, padding=(12, 10))
        tools.pack(fill=tk.X)
        for label, command in (
            ("Hoch", self.move_up),
            ("Runter", self.move_down),
            ("Ein/Aus", self.toggle_enabled),
            ("Duplizieren", self.duplicate_step),
            ("Loeschen", self.delete_step),
            ("Pause einfuegen", self.insert_wait),
        ):
            ttk.Button(tools, text=label, command=command).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(tools, text="Ab hier ausfuehren", command=lambda: self.run_from(False)).pack(side=tk.LEFT, padx=(18, 6))
        ttk.Button(tools, text="Nur diesen Schritt", command=lambda: self.run_from(True)).pack(side=tk.LEFT)

        footer = ttk.Frame(self, padding=(12, 0, 12, 12))
        footer.pack(fill=tk.X)
        ttk.Button(footer, text="Sichern und schliessen", command=self.save_and_close).pack(side=tk.RIGHT)
        ttk.Button(footer, text="Abbrechen", command=self.close).pack(side=tk.RIGHT, padx=(0, 6))

    # ------------------------------------------------------------------
    def _fill_list(self, keep: Optional[int] = None) -> None:
        selection = keep if keep is not None else self.current
        self.listbox.delete(0, tk.END)
        for index, step in enumerate(self.macro.steps):
            marker = " " if step.enabled else "x"
            pause = f"{step.delay_before:.1f}s " if step.delay_before >= 0.05 else "      "
            note = f"   ({step.note})" if step.note else ""
            self.listbox.insert(tk.END, f"[{marker}] {index + 1:>3}. {pause}{step.describe()}{note}")
            if not step.enabled:
                self.listbox.itemconfigure(index, foreground="#999999")
        if self.macro.steps:
            index = min(max(0, selection or 0), len(self.macro.steps) - 1)
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(index)
            self.listbox.see(index)
            self._show(index)
        else:
            self.current = None
            self._show(None)

    def _on_select(self, _event=None) -> None:
        selection = self.listbox.curselection()
        if selection:
            self._show(int(selection[0]))

    def _show(self, index: Optional[int]) -> None:
        self.current = index
        self.test_result.configure(text="")
        if index is None or index >= len(self.macro.steps):
            self.preview.configure(image="", text="Kein Bildausschnitt")
            self._preview_image = None
            self.preview_hint.configure(text="")
            for variable in (self.delay_var, self.threshold_var, self.timeout_var, self.text_var, self.note_var):
                variable.set("")
            return
        step = self.macro.steps[index]
        self.delay_var.set(f"{step.delay_before:.2f}")
        self.threshold_var.set("" if step.anchor is None or step.anchor.threshold is None
                               else f"{step.anchor.threshold:.2f}")
        self.timeout_var.set("" if step.timeout is None else f"{step.timeout:.1f}")
        self.error_var.set(ERROR_LABELS.get(step.on_error, ERROR_LABELS[ON_ERROR_ABORT]))
        if step.kind == TEXT:
            self.text_var.set(step.text)
        elif step.kind == KEY:
            self.text_var.set(step.key)
        elif step.kind == WAIT:
            self.text_var.set(f"{step.seconds:.2f}")
        else:
            self.text_var.set("")
        self.note_var.set(step.note)
        self._load_preview(step)

    def _load_preview(self, step: Step) -> None:
        if step.anchor is None or not step.anchor.template:
            self.preview.configure(image="", text="Dieser Schritt braucht kein Bild")
            self._preview_image = None
            self.preview_hint.configure(text="")
            return
        path = self.app.store.asset_path(self.slug, step.anchor.template)
        if not path.exists():
            self.preview.configure(image="", text="Bildausschnitt fehlt")
            self._preview_image = None
            return
        with Image.open(path) as handle:
            image = handle.convert("RGB")
        draw = ImageDraw.Draw(image)
        hx, hy = step.anchor.hotspot
        draw.line([(hx - 14, hy), (hx + 14, hy)], fill=(220, 30, 30), width=2)
        draw.line([(hx, hy - 14), (hx, hy + 14)], fill=(220, 30, 30), width=2)
        draw.ellipse([hx - 6, hy - 6, hx + 6, hy + 6], outline=(220, 30, 30), width=2)
        image.thumbnail(PREVIEW_MAX)
        self._preview_image = ImageTk.PhotoImage(image)
        self.preview.configure(image=self._preview_image, text="")
        self.preview_hint.configure(
            text="Diese Stelle wird auf dem Bildschirm wiedergesucht; das Kreuz ist der Klickpunkt."
        )

    # ------------------------------------------------------------------
    def _apply_fields(self) -> None:
        index = self.current
        if index is None or index >= len(self.macro.steps):
            return
        step = self.macro.steps[index]
        try:
            step.delay_before = max(0.0, float(self.delay_var.get().replace(",", ".") or 0))
        except ValueError:
            messagebox.showerror(APP_NAME, "Pause: bitte eine Zahl eingeben.", parent=self)
            return
        raw_threshold = self.threshold_var.get().replace(",", ".").strip()
        if step.anchor is not None:
            if not raw_threshold:
                step.anchor.threshold = None
            else:
                try:
                    step.anchor.threshold = min(0.99, max(0.3, float(raw_threshold)))
                except ValueError:
                    messagebox.showerror(APP_NAME, "Erkennungsschwelle: bitte eine Zahl eingeben.", parent=self)
                    return
        raw_timeout = self.timeout_var.get().replace(",", ".").strip()
        try:
            step.timeout = float(raw_timeout) if raw_timeout else None
        except ValueError:
            messagebox.showerror(APP_NAME, "Wartezeit: bitte eine Zahl eingeben.", parent=self)
            return
        step.on_error = ERROR_BY_LABEL.get(self.error_var.get(), ON_ERROR_ABORT)
        if step.kind == TEXT:
            step.text = self.text_var.get()
        elif step.kind == KEY:
            step.key = self.text_var.get().strip().lower()
        elif step.kind == WAIT:
            try:
                step.seconds = max(0.0, float(self.text_var.get().replace(",", ".") or step.seconds))
            except ValueError:
                pass
        step.note = self.note_var.get().strip()
        self._fill_list(index)

    def _selected_index(self) -> Optional[int]:
        if self.current is None:
            messagebox.showinfo(APP_NAME, "Bitte zuerst einen Schritt auswaehlen.", parent=self)
            return None
        return self.current

    def move_up(self) -> None:
        index = self._selected_index()
        if index is None or index == 0:
            return
        steps = self.macro.steps
        steps[index - 1], steps[index] = steps[index], steps[index - 1]
        self._fill_list(index - 1)

    def move_down(self) -> None:
        index = self._selected_index()
        if index is None or index >= len(self.macro.steps) - 1:
            return
        steps = self.macro.steps
        steps[index + 1], steps[index] = steps[index], steps[index + 1]
        self._fill_list(index + 1)

    def toggle_enabled(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        self.macro.steps[index].enabled = not self.macro.steps[index].enabled
        self._fill_list(index)

    def duplicate_step(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        original = self.macro.steps[index]
        copy = Step.from_dict(original.to_dict())
        self.macro.steps.insert(index + 1, copy)
        self._fill_list(index + 1)

    def delete_step(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        del self.macro.steps[index]
        self._fill_list(max(0, index - 1))

    def insert_wait(self) -> None:
        index = self.current if self.current is not None else len(self.macro.steps) - 1
        self.macro.steps.insert(index + 1, Step(kind=WAIT, seconds=1.0))
        self._fill_list(index + 1)

    # ------------------------------------------------------------------
    def test_recognition(self) -> None:
        index = self._selected_index()
        if index is None or self._loading:
            return
        step = self.macro.steps[index]
        if step.anchor is None:
            self.test_result.configure(text="Dieser Schritt sucht kein Bild.")
            return
        self._loading = True
        self.test_result.configure(text="Suche laeuft ...")

        def worker() -> None:
            text = ""
            try:
                from .anchors import AnchorLocator

                locator = AnchorLocator(self.app.screen, self.app.store, self.app.config)
                located = locator.locate_once(self.slug, step.anchor)
                if located is None:
                    text = "Bildausschnitt fehlt oder ist unbrauchbar."
                else:
                    threshold = (step.anchor.threshold
                                 if step.anchor.threshold is not None
                                 else float(self.app.config.get("match_threshold", 0.78)))
                    verdict = "gefunden" if located.score >= threshold else "NICHT sicher genug"
                    text = (f"Aehnlichkeit {located.score:.0%} ({verdict}, noetig {threshold:.0%})\n"
                            f"Position: x={located.point[0]:.0f}, y={located.point[1]:.0f}")
            except Exception as problem:
                text = f"Test nicht moeglich: {problem}"
            self.app._post(lambda: self._finish_test(text))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_test(self, text: str) -> None:
        self._loading = False
        try:
            self.test_result.configure(text=text)
        except tk.TclError:  # Fenster wurde inzwischen geschlossen
            pass

    def run_from(self, only_one: bool) -> None:
        index = self._selected_index()
        if index is None:
            return
        if not self._save(quiet=True):
            return
        self.app.run_macro(self.slug, start_index=index, only_one=only_one)

    # ------------------------------------------------------------------
    def _collect_header(self) -> bool:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror(APP_NAME, "Der Name darf nicht leer sein.", parent=self)
            return False
        self.macro.name = name
        try:
            self.macro.speed = max(0.1, min(10.0, float(self.speed_var.get().replace(",", ".") or 1.0)))
            self.macro.repeat = max(1, int(float(self.repeat_var.get() or 1)))
        except ValueError:
            messagebox.showerror(APP_NAME, "Tempo und Durchlaeufe muessen Zahlen sein.", parent=self)
            return False
        self.macro.hotkey = self.hotkey_var.get().strip()
        return True

    def _save(self, quiet: bool = False) -> bool:
        if self.current is not None:
            self._apply_fields()
        if not self._collect_header():
            return False
        self.app.store.save(self.macro)
        self.app.store.prune_assets(self.macro)
        self.app.cache.clear()
        self.app.refresh()
        self.app.select(self.slug)
        if not quiet:
            self.app.set_status(f"'{self.macro.name}' gesichert.")
        return True

    def save_and_close(self) -> None:
        if self._save():
            self.destroy()

    def close(self) -> None:
        self.destroy()
