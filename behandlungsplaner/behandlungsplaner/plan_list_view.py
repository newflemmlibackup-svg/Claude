"""Planungsliste unterhalb des OPG: Tabelle aller Positionen mit Zahnnummer,
Status, Kosten, Datum und Notiz, dazu eine Kosten-Zusammenfassung.

Die FDI-Zahnnummer steht bewusst ganz vorne und im Klartext ("17 · Molar oben
rechts") - sie ist beim Besprechen eines Plans die wichtigste Bezugsgroesse.
Positionen ohne Zahnzuordnung werden farblich hervorgehoben, damit auffaellt,
wo die Zuordnung noch fehlt.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import theme
from .fdi import ALL_FDI_TEETH, fdi_arch, fdi_side, fdi_tooth_class, is_valid_fdi
from .models import (
    KIND_ANCHOR_TYPE,
    KIND_LABELS,
    STATUS_DURCHGEFUEHRT,
    STATUS_GEPLANT,
)

COLUMNS = ("tooth", "kind", "status", "date", "cost", "note")
HEADINGS = {
    "tooth": "Zahn (FDI)", "kind": "Befund / Massnahme", "status": "Status",
    "date": "Datum", "cost": "Kosten", "note": "Notiz",
}

_TOOTH_CLASS_LABEL = {
    "schneidezahn": "Schneidezahn",
    "eckzahn": "Eckzahn",
    "praemolar": "Prämolar",
    "molar": "Molar",
}

UNASSIGNED_TEXT = "— nicht zugeordnet"


def fmt_eur(value: float) -> str:
    s = f"{value:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €"


def tooth_description(tooth: int) -> str:
    """Klartextbeschreibung einer FDI-Nummer, z. B. '17 · Molar oben rechts'."""
    if not is_valid_fdi(tooth):
        return str(tooth)
    return (f"{tooth} · {_TOOTH_CLASS_LABEL[fdi_tooth_class(tooth)]} "
            f"{fdi_arch(tooth)} {fdi_side(tooth)}")


def tooth_cell_text(item) -> str:
    """Was in der Zahnspalte steht - inkl. Bruecken-Spanne und Hinweis auf
    fehlende Zuordnung."""
    if item.bridge_teeth:
        first, last = item.bridge_teeth[0], item.bridge_teeth[-1]
        return f"{first} – {last} ({len(item.bridge_teeth)} Zähne)"
    if item.fdi_tooth is not None:
        return tooth_description(item.fdi_tooth)
    if KIND_ANCHOR_TYPE.get(item.kind) == "region":
        return "Kieferregion"
    return UNASSIGNED_TEXT


class EditItemDialog(tk.Toplevel):
    def __init__(self, parent, item, on_apply):
        super().__init__(parent)
        self.title("Position bearbeiten")
        self.resizable(False, False)
        self.configure(bg=theme.BG_SURFACE)
        self.item = item
        self.on_apply = on_apply
        self.transient(parent)
        self.grab_set()

        form = tk.Frame(self, bg=theme.BG_SURFACE,
                        padx=theme.PAD_LG, pady=theme.PAD_LG)
        form.pack(fill="both", expand=True)

        ttk.Label(form, text=KIND_LABELS[item.kind],
                  style="SurfaceHeading.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, theme.PAD_MD))

        row = 1
        ttk.Label(form, text="Zahn (FDI)", style="FieldLabel.TLabel").grid(
            row=row, column=0, sticky="w", pady=4)
        if item.bridge_teeth:
            self.tooth_var = tk.StringVar(value=tooth_cell_text(item))
            ttk.Label(form, textvariable=self.tooth_var, style="Surface.TLabel").grid(
                row=row, column=1, sticky="w")
        else:
            self.tooth_var = tk.StringVar(value=str(item.fdi_tooth) if item.fdi_tooth else "")
            ttk.Combobox(form, textvariable=self.tooth_var, width=12,
                         values=[""] + [str(t) for t in ALL_FDI_TEETH]).grid(
                row=row, column=1, sticky="w")

        row += 1
        ttk.Label(form, text="Kosten (EUR)", style="FieldLabel.TLabel").grid(
            row=row, column=0, sticky="w", pady=4)
        self.cost_var = tk.StringVar(value=f"{item.cost:.2f}")
        ttk.Entry(form, textvariable=self.cost_var, width=14).grid(row=row, column=1, sticky="w")

        row += 1
        ttk.Label(form, text="Leistung / Code", style="FieldLabel.TLabel").grid(
            row=row, column=0, sticky="w", pady=4)
        self.code_var = tk.StringVar(value=item.service_code)
        ttk.Entry(form, textvariable=self.code_var, width=18).grid(row=row, column=1, sticky="w")

        row += 1
        ttk.Label(form, text="Status", style="FieldLabel.TLabel").grid(
            row=row, column=0, sticky="w", pady=4)
        self.status_var = tk.StringVar(value=item.status)
        ttk.Combobox(form, textvariable=self.status_var, state="readonly", width=18,
                     values=[STATUS_GEPLANT, STATUS_DURCHGEFUEHRT]).grid(
            row=row, column=1, sticky="w")

        row += 1
        ttk.Label(form, text="Notiz", style="FieldLabel.TLabel").grid(
            row=row, column=0, sticky="nw", pady=4)
        self.note_text = tk.Text(form, width=32, height=4, font=theme.Fonts.body,
                                  relief="flat", highlightthickness=1,
                                  highlightbackground=theme.BORDER,
                                  highlightcolor=theme.ACCENT, bg=theme.BG_SURFACE)
        self.note_text.insert("1.0", item.note)
        self.note_text.grid(row=row, column=1, sticky="w")

        row += 1
        btns = tk.Frame(form, bg=theme.BG_SURFACE)
        btns.grid(row=row, column=0, columnspan=2, pady=(theme.PAD_MD, 0), sticky="e")
        ttk.Button(btns, text="Abbrechen", command=self.destroy).pack(side="right",
                                                                       padx=(theme.PAD_SM, 0))
        ttk.Button(btns, text="Speichern", style="Accent.TButton",
                   command=self._apply).pack(side="right")

    def _apply(self):
        if not self.item.bridge_teeth:
            tooth_text = self.tooth_var.get().strip()
            if tooth_text:
                try:
                    tooth = int(tooth_text)
                except ValueError:
                    tooth = None
                if tooth is not None and is_valid_fdi(tooth):
                    self.item.fdi_tooth = tooth
            else:
                self.item.fdi_tooth = None
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
        kwargs.setdefault("bg", theme.BG_APP)
        super().__init__(parent, **kwargs)
        self.plan = None
        self.on_row_selected = None   # callable(item_id)
        self.on_change = None         # callable()
        self._suppress_selection_event = False

        card = theme.card(self)
        card.pack(fill="both", expand=True, padx=theme.PAD_MD,
                  pady=(theme.PAD_SM, theme.PAD_MD))

        toolbar = tk.Frame(card, bg=theme.BG_SURFACE)
        toolbar.pack(fill="x", padx=theme.PAD_MD, pady=(theme.PAD_MD, theme.PAD_SM))
        ttk.Label(toolbar, text="Planungsliste", style="SurfaceHeading.TLabel").pack(side="left")

        ttk.Button(toolbar, text="Löschen", style="Danger.TButton",
                   command=self._delete_selected).pack(side="right")
        ttk.Button(toolbar, text="Status umschalten", style="Ghost.TButton",
                   command=self._toggle_status).pack(side="right", padx=theme.PAD_XS)
        ttk.Button(toolbar, text="Bearbeiten …", style="Ghost.TButton",
                   command=self._edit_selected).pack(side="right")

        table_wrap = tk.Frame(card, bg=theme.BG_SURFACE)
        table_wrap.pack(fill="both", expand=True, padx=theme.PAD_MD)

        self.tree = ttk.Treeview(table_wrap, columns=COLUMNS, show="headings",
                                  height=6, selectmode="browse")
        for col in COLUMNS:
            self.tree.heading(col, text=HEADINGS[col])
        self.tree.column("tooth", width=220, anchor="w")
        self.tree.column("kind", width=170, anchor="w")
        self.tree.column("status", width=120, anchor="w")
        self.tree.column("date", width=100, anchor="center")
        self.tree.column("cost", width=110, anchor="e")
        self.tree.column("note", width=240, anchor="w")
        theme.configure_row_tags(self.tree)

        scrollbar = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", lambda e: self._edit_selected())

        summary = tk.Frame(card, bg=theme.BG_SURFACE)
        summary.pack(fill="x", padx=theme.PAD_MD, pady=(theme.PAD_SM, theme.PAD_MD))
        self.count_label = ttk.Label(summary, text="", style="SurfaceMuted.TLabel")
        self.count_label.pack(side="left")
        self.total_label = ttk.Label(summary, text="", style="Total.TLabel")
        self.total_label.pack(side="right")
        self.split_label = ttk.Label(summary, text="", style="SurfaceMuted.TLabel")
        self.split_label.pack(side="right", padx=theme.PAD_MD)

    # ------------------------------------------------------------ Daten
    def refresh(self, plan):
        self.plan = plan
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())

        ordered = sorted(
            plan.items,
            key=lambda i: (i.fdi_tooth is None and not i.bridge_teeth,
                           i.bridge_teeth[0] if i.bridge_teeth else (i.fdi_tooth or 0),
                           i.kind),
        )
        for index, item in enumerate(ordered):
            status_text = "✓ durchgeführt" if item.status == STATUS_DURCHGEFUEHRT else "geplant"
            date_text = (item.done_date if item.status == STATUS_DURCHGEFUEHRT and item.done_date
                         else item.planned_date)
            tags = ["even" if index % 2 == 0 else "odd"]
            if item.status == STATUS_DURCHGEFUEHRT:
                tags.append("done")
            elif tooth_cell_text(item) == UNASSIGNED_TEXT:
                tags.append("unassigned")

            self.tree.insert("", "end", iid=item.id, tags=tuple(tags), values=(
                tooth_cell_text(item),
                KIND_LABELS[item.kind],
                status_text,
                date_text or "–",
                fmt_eur(item.cost),
                item.note,
            ))

        if selected and selected[0] in self.tree.get_children():
            self.tree.selection_set(selected[0])

        total_open = plan.total_cost(status=STATUS_GEPLANT)
        total_done = plan.total_cost(status=STATUS_DURCHGEFUEHRT)
        unassigned = sum(1 for i in plan.items if tooth_cell_text(i) == UNASSIGNED_TEXT)

        count_text = f"{len(plan.items)} Position(en)"
        if unassigned:
            count_text += f"  ·  {unassigned} ohne Zahnzuordnung"
        self.count_label.config(text=count_text)
        self.split_label.config(
            text=f"offen {fmt_eur(total_open)}   ·   durchgeführt {fmt_eur(total_done)}")
        self.total_label.config(text=f"Gesamt {fmt_eur(plan.total_cost())}")

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
