"""Planungsliste unterhalb des OPG: Tabelle aller Positionen mit Zahn, Status,
Kosten, Datum und Notiz, dazu eine Kosten-Zusammenfassung."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .fdi import ALL_FDI_TEETH
from .models import KIND_LABELS, STATUS_DURCHGEFUEHRT, STATUS_GEPLANT

COLUMNS = ("kind", "tooth", "status", "date", "cost", "note")
HEADINGS = {
    "kind": "Typ", "tooth": "Zahn (FDI)", "status": "Status",
    "date": "Datum", "cost": "Kosten (EUR)", "note": "Notiz",
}


def _fmt_eur(value: float) -> str:
    s = f"{value:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €"


class EditItemDialog(tk.Toplevel):
    def __init__(self, parent, item, on_apply):
        super().__init__(parent)
        self.title("Position bearbeiten")
        self.resizable(False, False)
        self.item = item
        self.on_apply = on_apply
        self.transient(parent)
        self.grab_set()

        form = ttk.Frame(self, padding=12)
        form.pack(fill="both", expand=True)

        ttk.Label(form, text=KIND_LABELS[item.kind], font=("Helvetica", 11, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        ttk.Label(form, text="Zahn (FDI):").grid(row=1, column=0, sticky="w", pady=3)
        tooth_values = [""] + [str(t) for t in ALL_FDI_TEETH]
        self.tooth_var = tk.StringVar(value=str(item.fdi_tooth) if item.fdi_tooth else "")
        ttk.Combobox(form, textvariable=self.tooth_var, values=tooth_values, width=10,
                     state="readonly" if item.bridge_teeth else "normal").grid(row=1, column=1, sticky="w")

        ttk.Label(form, text="Kosten (EUR):").grid(row=2, column=0, sticky="w", pady=3)
        self.cost_var = tk.StringVar(value=f"{item.cost:.2f}")
        ttk.Entry(form, textvariable=self.cost_var, width=12).grid(row=2, column=1, sticky="w")

        ttk.Label(form, text="Leistung/Code:").grid(row=3, column=0, sticky="w", pady=3)
        self.code_var = tk.StringVar(value=item.service_code)
        ttk.Entry(form, textvariable=self.code_var, width=16).grid(row=3, column=1, sticky="w")

        ttk.Label(form, text="Status:").grid(row=4, column=0, sticky="w", pady=3)
        self.status_var = tk.StringVar(value=item.status)
        status_box = ttk.Combobox(form, textvariable=self.status_var, state="readonly", width=16,
                                   values=[STATUS_GEPLANT, STATUS_DURCHGEFUEHRT])
        status_box.grid(row=4, column=1, sticky="w")

        ttk.Label(form, text="Notiz:").grid(row=5, column=0, sticky="nw", pady=3)
        self.note_text = tk.Text(form, width=28, height=4)
        self.note_text.insert("1.0", item.note)
        self.note_text.grid(row=5, column=1, sticky="w")

        btns = ttk.Frame(form)
        btns.grid(row=6, column=0, columnspan=2, pady=(10, 0), sticky="e")
        ttk.Button(btns, text="Abbrechen", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Speichern", command=self._apply).pack(side="right")

    def _apply(self):
        tooth_text = self.tooth_var.get().strip()
        if not self.item.bridge_teeth:
            self.item.fdi_tooth = int(tooth_text) if tooth_text else None
        try:
            self.item.cost = float(self.cost_var.get().replace(",", "."))
        except ValueError:
            pass
        self.item.service_code = self.code_var.get().strip()
        self.item.note = self.note_text.get("1.0", "end").strip()
        if self.status_var.get() == STATUS_DURCHGEFUEHRT and self.item.status != STATUS_DURCHGEFUEHRT:
            self.item.mark_done()
        elif self.status_var.get() == STATUS_GEPLANT and self.item.status != STATUS_GEPLANT:
            self.item.mark_planned()
        else:
            self.item.touch()
        self.destroy()
        self.on_apply()


class PlanListView(tk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.plan = None
        self.on_row_selected = None   # callable(item_id)
        self.on_change = None         # callable()
        self._suppress_selection_event = False

        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=4, pady=(4, 0))
        ttk.Button(toolbar, text="Bearbeiten...", command=self._edit_selected).pack(side="left")
        ttk.Button(toolbar, text="Status umschalten", command=self._toggle_status).pack(side="left", padx=4)
        ttk.Button(toolbar, text="Löschen", command=self._delete_selected).pack(side="left")

        self.tree = ttk.Treeview(self, columns=COLUMNS, show="headings", height=7, selectmode="browse")
        for col in COLUMNS:
            self.tree.heading(col, text=HEADINGS[col])
        self.tree.column("kind", width=140)
        self.tree.column("tooth", width=80, anchor="center")
        self.tree.column("status", width=100, anchor="center")
        self.tree.column("date", width=90, anchor="center")
        self.tree.column("cost", width=100, anchor="e")
        self.tree.column("note", width=260)
        self.tree.pack(fill="both", expand=True, padx=4, pady=4)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", lambda e: self._edit_selected())

        summary = ttk.Frame(self)
        summary.pack(fill="x", padx=4, pady=(0, 6))
        self.summary_label = ttk.Label(summary, text="", font=("Helvetica", 9, "bold"))
        self.summary_label.pack(anchor="e")

    # ------------------------------------------------------------ Daten
    def refresh(self, plan):
        self.plan = plan
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for item in sorted(plan.items, key=lambda i: (i.fdi_tooth is None, i.fdi_tooth or 0, i.kind)):
            tooth_text = "-"
            if item.bridge_teeth:
                tooth_text = f"{item.bridge_teeth[0]}–{item.bridge_teeth[-1]}"
            elif item.fdi_tooth is not None:
                tooth_text = str(item.fdi_tooth)
            status_text = "durchgeführt" if item.status == STATUS_DURCHGEFUEHRT else "geplant"
            date_text = item.done_date if item.status == STATUS_DURCHGEFUEHRT and item.done_date else item.planned_date
            self.tree.insert("", "end", iid=item.id, values=(
                KIND_LABELS[item.kind], tooth_text, status_text, date_text or "-",
                _fmt_eur(item.cost), item.note,
            ))
        if selected and selected[0] in self.tree.get_children():
            self.tree.selection_set(selected[0])

        total_open = plan.total_cost(status=STATUS_GEPLANT)
        total_done = plan.total_cost(status=STATUS_DURCHGEFUEHRT)
        total_all = plan.total_cost()
        self.summary_label.config(
            text=f"{len(plan.items)} Position(en)  |  offen: {_fmt_eur(total_open)}  |  "
                 f"durchgeführt: {_fmt_eur(total_done)}  |  gesamt: {_fmt_eur(total_all)}"
        )

    def select_row(self, item_id):
        # <<TreeviewSelect>> wird von Tk asynchron ueber die Event-Queue
        # ausgeloest, nicht synchron durch selection_set(). Das Suppress-Flag
        # darf deshalb erst wieder im naechsten Idle-Zyklus zurueckgesetzt
        # werden - sonst laeuft _on_tree_select trotzdem noch durch.
        self._suppress_selection_event = True
        if item_id and item_id in self.tree.get_children():
            self.tree.selection_set(item_id)
            self.tree.see(item_id)
        else:
            self.tree.selection_remove(*self.tree.selection())
        self.after_idle(self._clear_suppress_flag)

    def _clear_suppress_flag(self):
        self._suppress_selection_event = False

    # ------------------------------------------------------------ Events
    def _selected_item(self):
        sel = self.tree.selection()
        if not sel or not self.plan:
            return None
        return self.plan.get_item(sel[0])

    def _on_tree_select(self, _event):
        if self._suppress_selection_event or not self.on_row_selected:
            return
        sel = self.tree.selection()
        self.on_row_selected(sel[0] if sel else None)

    def _edit_selected(self):
        item = self._selected_item()
        if not item:
            return
        EditItemDialog(self, item, on_apply=self._notify_change)

    def _toggle_status(self):
        item = self._selected_item()
        if not item:
            return
        if item.status == STATUS_GEPLANT:
            item.mark_done()
        else:
            item.mark_planned()
        self._notify_change()

    def _delete_selected(self):
        item = self._selected_item()
        if not item or not self.plan:
            return
        self.plan.remove_item(item.id)
        self._notify_change()

    def _notify_change(self):
        if self.plan is not None:
            self.refresh(self.plan)
        if self.on_change:
            self.on_change()
