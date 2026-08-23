"""Zentrale Design-Tokens und ttk-Styling.

Tkinter sieht in der Voreinstellung nach Motif der 90er aus: graue
3D-Rahmen, enge Abstaende, Systemschrift in Minimalgroesse. Dieses Modul
legt daher ein flaches, ruhiges Erscheinungsbild ueber die Anwendung:
weiche Graustufen, eine einzige Akzentfarbe, grosszuegige Innenabstaende und
plattformgerechte Schriften.
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# --------------------------------------------------------------- Farbtokens
BG_APP = "#f4f5f7"        # Fensterhintergrund
BG_SURFACE = "#ffffff"     # Karten/Panels
BG_SUBTLE = "#eceef1"      # Sekundaerflaechen, Kopfzeilen
BG_CANVAS = "#1f2226"      # Umgebung des Roentgenbilds
BORDER = "#dcdfe4"
BORDER_STRONG = "#c3c8d0"

TEXT = "#1d2129"
TEXT_MUTED = "#6b7280"
TEXT_ON_ACCENT = "#ffffff"

ACCENT = "#2f7ef4"
ACCENT_HOVER = "#1f6ae0"
ACCENT_SOFT = "#e5efff"

SUCCESS = "#12875b"
SUCCESS_SOFT = "#e2f5ec"
WARNING = "#b45309"
WARNING_SOFT = "#fdf1de"
DANGER = "#c0392b"

ROW_STRIPE = "#f7f8fa"
SELECTION_BG = "#dcebff"

# ------------------------------------------------------------------ Abstaende
PAD_XS = 4
PAD_SM = 8
PAD_MD = 14
PAD_LG = 22

RADIUS_HINT = 6  # Tk kann keine echten Rundungen - nur als Layout-Richtwert


def font_family() -> str:
    """Plattformtypische Oberflaechenschrift."""
    if sys.platform == "darwin":
        return "SF Pro Text"
    if sys.platform.startswith("win"):
        return "Segoe UI"
    return "DejaVu Sans"


def _first_available_family(root: tk.Misc, candidates) -> str:
    available = set(tkfont.families(root))
    for name in candidates:
        if name in available:
            return name
    return "TkDefaultFont"


def resolve_family(root: tk.Misc) -> str:
    """Erste tatsaechlich installierte Schrift aus der Wunschliste - sonst
    faellt Tk stumm auf eine Ersatzschrift zurueck, die je nach System sehr
    unterschiedlich aussieht."""
    preferred = [font_family(), "SF Pro Text", "Helvetica Neue", "Segoe UI",
                 "DejaVu Sans", "Arial", "Helvetica"]
    return _first_available_family(root, preferred)


class Fonts:
    """Nach `apply_theme()` gefuellte Schriftdefinitionen."""
    family = "TkDefaultFont"
    body = ("TkDefaultFont", 11)
    body_bold = ("TkDefaultFont", 11, "bold")
    small = ("TkDefaultFont", 9)
    label = ("TkDefaultFont", 10)
    heading = ("TkDefaultFont", 14, "bold")
    title = ("TkDefaultFont", 20, "bold")
    mono_number = ("TkDefaultFont", 11)


def apply_theme(root: tk.Misc) -> None:
    """Setzt Basistheme, Farben, Schriften und Widget-Styles."""
    style = ttk.Style(root)
    # 'clam' ist das einzige mitgelieferte Theme, dessen Farben sich
    # vollstaendig ueberschreiben lassen - aqua/vista ignorieren viele Optionen.
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    family = resolve_family(root)
    Fonts.family = family
    Fonts.body = (family, 11)
    Fonts.body_bold = (family, 11, "bold")
    Fonts.small = (family, 9)
    Fonts.label = (family, 10)
    Fonts.heading = (family, 14, "bold")
    Fonts.title = (family, 20, "bold")
    Fonts.mono_number = (family, 11)

    root.option_add("*Font", Fonts.body)
    try:
        root.configure(bg=BG_APP)
    except tk.TclError:
        pass

    # --- Flaechen ---
    style.configure("TFrame", background=BG_APP)
    style.configure("Surface.TFrame", background=BG_SURFACE)
    style.configure("Subtle.TFrame", background=BG_SUBTLE)
    style.configure("Toolbar.TFrame", background=BG_SURFACE)

    # --- Text ---
    style.configure("TLabel", background=BG_APP, foreground=TEXT, font=Fonts.body)
    style.configure("Surface.TLabel", background=BG_SURFACE, foreground=TEXT)
    style.configure("Muted.TLabel", background=BG_APP, foreground=TEXT_MUTED, font=Fonts.small)
    style.configure("SurfaceMuted.TLabel", background=BG_SURFACE,
                    foreground=TEXT_MUTED, font=Fonts.small)
    style.configure("Heading.TLabel", background=BG_APP, foreground=TEXT, font=Fonts.heading)
    style.configure("SurfaceHeading.TLabel", background=BG_SURFACE, foreground=TEXT,
                    font=Fonts.heading)
    style.configure("Title.TLabel", background=BG_APP, foreground=TEXT, font=Fonts.title)
    style.configure("FieldLabel.TLabel", background=BG_SURFACE, foreground=TEXT_MUTED,
                    font=Fonts.small)
    style.configure("Total.TLabel", background=BG_SURFACE, foreground=TEXT,
                    font=(family, 12, "bold"))

    # --- Buttons: flach, ohne 3D-Rahmen ---
    style.configure(
        "TButton", background=BG_SUBTLE, foreground=TEXT, font=Fonts.body,
        borderwidth=0, focusthickness=0, padding=(PAD_MD, PAD_SM), relief="flat",
    )
    style.map(
        "TButton",
        background=[("pressed", BORDER_STRONG), ("active", BORDER), ("disabled", BG_SUBTLE)],
        foreground=[("disabled", TEXT_MUTED)],
    )

    style.configure(
        "Accent.TButton", background=ACCENT, foreground=TEXT_ON_ACCENT,
        font=Fonts.body_bold, borderwidth=0, padding=(PAD_MD, PAD_SM), relief="flat",
    )
    style.map(
        "Accent.TButton",
        background=[("pressed", ACCENT_HOVER), ("active", ACCENT_HOVER),
                    ("disabled", BORDER_STRONG)],
        foreground=[("disabled", "#ffffff")],
    )

    # "Ghost" bleibt zurueckhaltend, braucht aber eine sichtbare Flaeche -
    # ohne sie liest sich der Knopf wie blosser Text und wirkt nicht klickbar.
    style.configure(
        "Ghost.TButton", background=BG_SUBTLE, foreground=TEXT,
        borderwidth=0, padding=(PAD_MD, PAD_XS + 2), relief="flat",
    )
    style.map("Ghost.TButton",
              background=[("pressed", BORDER_STRONG), ("active", BORDER)])

    style.configure(
        "Danger.TButton", background="#fbeae7", foreground=DANGER,
        borderwidth=0, padding=(PAD_MD, PAD_XS + 2), relief="flat",
    )
    style.map("Danger.TButton",
              background=[("pressed", "#f0c7c0"), ("active", "#f6d9d5")])

    # --- Eingabefelder ---
    for entry_style in ("TEntry", "TCombobox"):
        style.configure(
            entry_style, fieldbackground=BG_SURFACE, background=BG_SURFACE,
            foreground=TEXT, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
            borderwidth=1, relief="flat", padding=PAD_XS, arrowcolor=TEXT_MUTED,
        )
        style.map(entry_style,
                  bordercolor=[("focus", ACCENT)],
                  lightcolor=[("focus", ACCENT)],
                  darkcolor=[("focus", ACCENT)])

    style.configure("TCheckbutton", background=BG_SURFACE, foreground=TEXT, font=Fonts.body)
    style.map("TCheckbutton", background=[("active", BG_SURFACE)])

    # --- Tabellen ---
    style.configure(
        "Treeview", background=BG_SURFACE, fieldbackground=BG_SURFACE, foreground=TEXT,
        rowheight=30, borderwidth=0, font=Fonts.body,
    )
    style.map("Treeview",
              background=[("selected", SELECTION_BG)],
              foreground=[("selected", TEXT)])
    style.configure(
        "Treeview.Heading", background=BG_SUBTLE, foreground=TEXT_MUTED,
        font=(family, 9, "bold"), relief="flat", borderwidth=0, padding=(PAD_SM, PAD_SM),
    )
    style.map("Treeview.Heading", background=[("active", BORDER)])
    # Der Standard-Rahmen um Treeviews wirkt wie ein eingelassenes 90er-Feld.
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    style.configure("TSeparator", background=BORDER)
    style.configure("TPanedwindow", background=BG_APP)
    style.configure("Vertical.TScrollbar", background=BG_SUBTLE, troughcolor=BG_APP,
                    borderwidth=0, arrowcolor=TEXT_MUTED)
    style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=BG_SUBTLE,
                    borderwidth=0)


def configure_row_tags(tree: ttk.Treeview) -> None:
    """Zebrastreifen und Statusfarben fuer eine Tabelle registrieren."""
    tree.tag_configure("odd", background=ROW_STRIPE)
    tree.tag_configure("even", background=BG_SURFACE)
    tree.tag_configure("done", foreground=SUCCESS)
    tree.tag_configure("unassigned", foreground=WARNING)


def card(parent, **kwargs) -> tk.Frame:
    """Flaeche mit heller Fuellung und feiner Umrandung statt 3D-Rahmen."""
    kwargs.setdefault("bg", BG_SURFACE)
    kwargs.setdefault("highlightbackground", BORDER)
    kwargs.setdefault("highlightcolor", BORDER)
    kwargs.setdefault("highlightthickness", 1)
    kwargs.setdefault("bd", 0)
    return tk.Frame(parent, **kwargs)
