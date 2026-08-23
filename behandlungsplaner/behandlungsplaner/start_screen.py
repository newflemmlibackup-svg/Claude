"""Startbildschirm: Uebersicht der vorhandenen Behandlungsplaene aus dem
Praxis-Datenordner sowie Aktionen zum Anlegen/Oeffnen/Duplizieren/Loeschen."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from . import storage, theme

COLUMNS = ("patient", "date", "practitioner", "items", "cost", "updated")
HEADINGS = {
    "patient": "Patient/-in", "date": "Datum", "practitioner": "Behandler/-in",
    "items": "Positionen", "cost": "Summe", "updated": "Zuletzt geändert",
}


def _fmt_eur(value: float) -> str:
    s = f"{value:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €"


class StartScreen(tk.Frame):
    def __init__(self, parent, data_root, **kwargs):
        kwargs.setdefault("bg", theme.BG_APP)
        super().__init__(parent, **kwargs)
        self.data_root = data_root
        self.on_new = None          # callable()
        self.on_open = None         # callable(folder)
        self.on_duplicate = None    # callable(folder)
        self.on_delete = None       # callable(folder)
        self._summaries = {}

        header = tk.Frame(self, bg=theme.BG_APP)
        header.pack(fill="x", padx=theme.PAD_LG, pady=(theme.PAD_LG, theme.PAD_MD))

        titles = tk.Frame(header, bg=theme.BG_APP)
        titles.pack(side="left")
        ttk.Label(titles, text="Behandlungspläne", style="Title.TLabel").pack(anchor="w")
        ttk.Label(titles, text="OPG importieren, Befunde einzeichnen, Kosten planen.",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 0))

        ttk.Button(header, text="＋  Neuer Plan", style="Accent.TButton",
                   command=lambda: self.on_new and self.on_new()).pack(side="right")

        card = theme.card(self)
        card.pack(fill="both", expand=True, padx=theme.PAD_LG)

        table_wrap = tk.Frame(card, bg=theme.BG_SURFACE)
        table_wrap.pack(fill="both", expand=True, padx=theme.PAD_MD, pady=theme.PAD_MD)

        self.tree = ttk.Treeview(table_wrap, columns=COLUMNS, show="headings",
                                  selectmode="browse")
        for col in COLUMNS:
            self.tree.heading(col, text=HEADINGS[col])
        self.tree.column("patient", width=250, anchor="w")
        self.tree.column("date", width=110, anchor="center")
        self.tree.column("practitioner", width=170, anchor="w")
        self.tree.column("items", width=100, anchor="center")
        self.tree.column("cost", width=130, anchor="e")
        self.tree.column("updated", width=160, anchor="w")
        theme.configure_row_tags(self.tree)

        scrollbar = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self._open_selected())

        self.empty_label = ttk.Label(
            card,
            text="Noch keine Pläne vorhanden.\nMit „Neuer Plan“ ein OPG importieren.",
            style="SurfaceMuted.TLabel", justify="center",
        )

        btns = tk.Frame(self, bg=theme.BG_APP)
        btns.pack(fill="x", padx=theme.PAD_LG, pady=theme.PAD_MD)
        ttk.Button(btns, text="Öffnen", style="Accent.TButton",
                   command=self._open_selected).pack(side="left")
        ttk.Button(btns, text="Folgeplan anlegen",
                   command=self._duplicate_selected).pack(side="left", padx=theme.PAD_SM)
        ttk.Button(btns, text="Löschen", style="Danger.TButton",
                   command=self._delete_selected).pack(side="left")
        ttk.Button(btns, text="Aktualisieren", style="Ghost.TButton",
                   command=self.refresh).pack(side="right")

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self._summaries = {}
        summaries = storage.list_plans(self.data_root)

        for index, summary in enumerate(summaries):
            key = str(summary.folder)
            self._summaries[key] = summary
            self.tree.insert("", "end", iid=key,
                              tags=("even" if index % 2 == 0 else "odd",),
                              values=(
                                  summary.patient_name,
                                  summary.plan_date,
                                  summary.practitioner or "–",
                                  summary.item_count,
                                  _fmt_eur(summary.total_cost),
                                  summary.updated_at[:16].replace("T", " "),
                              ))

        if summaries:
            self.empty_label.pack_forget()
        else:
            self.empty_label.pack(pady=theme.PAD_LG)

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
            "Plan löschen",
            f"Plan von „{summary.patient_name}“ ({summary.plan_date}) endgültig löschen?\n"
            "Dies kann nicht rückgängig gemacht werden.",
        ):
            if self.on_delete:
                self.on_delete(folder)
            self.refresh()
