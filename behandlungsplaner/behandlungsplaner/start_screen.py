"""Startbildschirm: Liste vorhandener Behandlungsplaene (aus dem
Praxis-Datenordner) sowie Aktionen zum Anlegen/Oeffnen/Duplizieren/Loeschen."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from . import storage

COLUMNS = ("patient", "date", "practitioner", "items", "cost", "updated")
HEADINGS = {
    "patient": "Patient/-in", "date": "Datum", "practitioner": "Behandler/-in",
    "items": "Positionen", "cost": "Summe", "updated": "Zuletzt geaendert",
}


def _fmt_eur(value: float) -> str:
    s = f"{value:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €"


class StartScreen(tk.Frame):
    def __init__(self, parent, data_root, **kwargs):
        super().__init__(parent, **kwargs)
        self.data_root = data_root
        self.on_new = None          # callable()
        self.on_open = None         # callable(folder)
        self.on_duplicate = None    # callable(folder)
        self.on_delete = None       # callable(folder)
        self._summaries = {}

        header = ttk.Frame(self)
        header.pack(fill="x", padx=16, pady=(16, 8))
        ttk.Label(header, text="Behandlungsplaene", font=("Helvetica", 16, "bold")).pack(side="left")
        ttk.Button(header, text="Neuer Plan...", command=lambda: self.on_new and self.on_new()).pack(side="right")

        self.tree = ttk.Treeview(self, columns=COLUMNS, show="headings", selectmode="browse")
        for col in COLUMNS:
            self.tree.heading(col, text=HEADINGS[col])
        self.tree.column("patient", width=220)
        self.tree.column("date", width=100, anchor="center")
        self.tree.column("practitioner", width=150)
        self.tree.column("items", width=90, anchor="center")
        self.tree.column("cost", width=110, anchor="e")
        self.tree.column("updated", width=150)
        self.tree.pack(fill="both", expand=True, padx=16, pady=8)
        self.tree.bind("<Double-1>", lambda e: self._open_selected())

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=16, pady=(0, 16))
        ttk.Button(btns, text="Oeffnen", command=self._open_selected).pack(side="left")
        ttk.Button(btns, text="Folgeplan (dupliziert Bild+Positionen)",
                   command=self._duplicate_selected).pack(side="left", padx=6)
        ttk.Button(btns, text="Loeschen", command=self._delete_selected).pack(side="left")
        ttk.Button(btns, text="Aktualisieren", command=self.refresh).pack(side="right")

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self._summaries = {}
        for summary in storage.list_plans(self.data_root):
            key = str(summary.folder)
            self._summaries[key] = summary
            self.tree.insert("", "end", iid=key, values=(
                summary.patient_name, summary.plan_date, summary.practitioner,
                summary.item_count, _fmt_eur(summary.total_cost), summary.updated_at[:16].replace("T", " "),
            ))

    def _selected_folder(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self._summaries[sel[0]].folder

    def _open_selected(self):
        folder = self._selected_folder()
        if folder and self.on_open:
            self.on_open(folder)

    def _duplicate_selected(self):
        folder = self._selected_folder()
        if folder and self.on_duplicate:
            self.on_duplicate(folder)

    def _delete_selected(self):
        folder = self._selected_folder()
        if not folder:
            return
        summary = self._summaries[str(folder)]
        if messagebox.askyesno(
            "Plan loeschen",
            f"Plan von '{summary.patient_name}' ({summary.plan_date}) endgueltig loeschen?\n"
            "Dies kann nicht rueckgaengig gemacht werden.",
        ):
            if self.on_delete:
                self.on_delete(folder)
            self.refresh()
