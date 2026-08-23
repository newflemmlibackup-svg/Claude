"""Bedienoberflaeche: Buttons anlegen, aufnehmen, abspielen."""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable, Dict, Optional

from . import APP_NAME, permissions
from .anchors import AnchorFactory, TemplateCache
from .config import data_root, load_config, save_config
from .hotkeys import HotkeyManager, normalize, pretty
from .models import Macro
from .player import Player
from .recorder import Recorder, RecordingSession
from .screen import ScreenBuffer, get_screen
from .storage import Store

TILE_WIDTH = 210
TILE_HEIGHT = 96


class KlickpilotApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.config = load_config()
        self.store = Store(data_root(self.config))
        self.cache = TemplateCache(self.store)
        self.hotkeys = HotkeyManager()
        self.ui_queue: "queue.Queue[Callable[[], None]]" = queue.Queue()

        self._screen = None
        self._inputs = None
        self.recorder: Optional[Recorder] = None
        self.recording_slug: Optional[str] = None
        self.recording_hud: Optional[tk.Toplevel] = None
        self.player: Optional[Player] = None
        self.player_thread: Optional[threading.Thread] = None
        self.selected: Optional[str] = None
        self.tiles: Dict[str, tk.Widget] = {}
        self._recording_append = False
        self._recording_macro: Optional[Macro] = None

        root.title(APP_NAME)
        root.geometry("760x600")
        root.minsize(560, 420)
        self._build_menu()
        self._build_widgets()
        self.refresh()
        self._pump()
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.after(400, self._check_permissions)

    # ------------------------------------------------------------------
    # Aufbau der Oberflaeche
    # ------------------------------------------------------------------
    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        macro_menu = tk.Menu(menubar, tearoff=0)
        macro_menu.add_command(label="Neuer Button (aufnehmen)...", command=self.new_button)
        macro_menu.add_command(label="Bearbeiten...", command=self.edit_selected)
        macro_menu.add_command(label="Umbenennen...", command=self.rename_selected)
        macro_menu.add_command(label="Tastenkuerzel...", command=self.hotkey_selected)
        macro_menu.add_separator()
        macro_menu.add_command(label="Duplizieren", command=self.duplicate_selected)
        macro_menu.add_command(label="Loeschen", command=self.delete_selected)
        macro_menu.add_separator()
        macro_menu.add_command(label="Exportieren...", command=self.export_selected)
        macro_menu.add_command(label="Importieren...", command=self.import_macro)
        menubar.add_cascade(label="Button", menu=macro_menu)

        extra = tk.Menu(menubar, tearoff=0)
        extra.add_command(label="Einstellungen...", command=self.open_settings)
        extra.add_command(label="Datenordner oeffnen", command=self.open_data_folder)
        extra.add_separator()
        extra.add_command(label="Freigaben pruefen", command=lambda: self._check_permissions(True))
        extra.add_command(label="Hilfe", command=self.show_help)
        menubar.add_cascade(label="Extras", menu=extra)
        try:
            self.root.config(menu=menubar)
        except tk.TclError:  # pragma: no cover
            pass

    def _build_widgets(self) -> None:
        toolbar = ttk.Frame(self.root, padding=(10, 8))
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="+ Neuer Button", command=self.new_button).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Bearbeiten", command=self.edit_selected).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(toolbar, text="Loeschen", command=self.delete_selected).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(toolbar, text="Einstellungen", command=self.open_settings).pack(side=tk.RIGHT)
        self.stop_button = ttk.Button(toolbar, text="Stopp", command=self.stop_everything, state=tk.DISABLED)
        self.stop_button.pack(side=tk.RIGHT, padx=(0, 6))

        body = ttk.Frame(self.root)
        body.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(body, highlightthickness=0, background="#f2f2f2")
        scrollbar = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.grid_frame = ttk.Frame(self.canvas, padding=10)
        self._grid_window = self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.grid_frame.bind(
            "<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.bind(
            "<Configure>", lambda event: self.canvas.itemconfigure(self._grid_window, width=event.width)
        )
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.bind_all(sequence, self._on_wheel)

        bottom = ttk.Frame(self.root, padding=(10, 6))
        bottom.pack(fill=tk.X)
        self.status = tk.StringVar(value="Bereit.")
        ttk.Label(bottom, textvariable=self.status).pack(side=tk.LEFT)
        self.log_widget = tk.Text(self.root, height=7, wrap=tk.WORD, state=tk.DISABLED,
                                  background="#111111", foreground="#dddddd", relief=tk.FLAT)
        self.log_widget.pack(fill=tk.X, padx=10, pady=(0, 10))
        self.root.bind("<Escape>", lambda _event: self.stop_everything())

    def _on_wheel(self, event) -> None:
        if event.num == 4:
            steps = -3
        elif event.num == 5:
            steps = 3
        else:
            # macOS liefert kleine Werte, andere Systeme Vielfache von 120.
            delta = event.delta
            steps = -delta if abs(delta) < 20 else -delta // 120 * 3
        self.canvas.yview_scroll(int(steps) or (1 if steps > 0 else -1), "units")

    # ------------------------------------------------------------------
    # Buttonraster
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        for child in self.grid_frame.winfo_children():
            child.destroy()
        self.tiles.clear()
        refs = self.store.list_macros()
        if not refs:
            hint = ttk.Label(
                self.grid_frame,
                text=("Noch keine Buttons vorhanden.\n\n"
                      "Mit '+ Neuer Button' einen Namen vergeben - danach wird alles\n"
                      "aufgezeichnet, was Sie mit Maus und Tastatur tun. Beenden mit "
                      f"{pretty(self.config.get('stop_hotkey', '<f9>'))}."),
                justify=tk.LEFT,
            )
            hint.grid(row=0, column=0, sticky="w", padx=6, pady=6)
            return
        columns = max(1, int(self.config.get("columns", 3)))
        for index, ref in enumerate(refs):
            tile = self._build_tile(ref)
            tile.grid(row=index // columns, column=index % columns, padx=6, pady=6, sticky="nsew")
            self.tiles[ref.slug] = tile
        for column in range(columns):
            self.grid_frame.columnconfigure(column, weight=1)
        self._apply_hotkeys()

    def _build_tile(self, ref) -> tk.Widget:
        frame = tk.Frame(self.grid_frame, bd=1, relief=tk.SOLID, background="#ffffff",
                         highlightthickness=2, highlightbackground="#ffffff")
        frame.configure(width=TILE_WIDTH, height=TILE_HEIGHT)
        run = tk.Button(
            frame, text=ref.name, wraplength=TILE_WIDTH - 24, justify=tk.CENTER,
            command=lambda slug=ref.slug: self.run_macro(slug), height=2,
        )
        run.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 2))
        footer = tk.Frame(frame, background="#ffffff")
        footer.pack(fill=tk.X, padx=8, pady=(0, 6))
        subtitle = f"{ref.steps} Schritte"
        if ref.hotkey:
            subtitle += f"   {pretty(normalize(ref.hotkey))}"
        tk.Label(footer, text=subtitle, background="#ffffff", foreground="#666666").pack(side=tk.LEFT)
        menu_button = tk.Button(footer, text="...", width=3,
                                command=lambda slug=ref.slug, widget=frame: self._tile_menu(slug, widget))
        menu_button.pack(side=tk.RIGHT)
        for widget in (frame, footer):
            widget.bind("<Button-1>", lambda _event, slug=ref.slug: self.select(slug))
            widget.bind("<Button-2>", lambda event, slug=ref.slug: self._tile_menu(slug, event.widget, event))
            widget.bind("<Button-3>", lambda event, slug=ref.slug: self._tile_menu(slug, event.widget, event))
            widget.bind("<Control-Button-1>", lambda event, slug=ref.slug: self._tile_menu(slug, event.widget, event))
        run.bind("<Button-2>", lambda event, slug=ref.slug: self._tile_menu(slug, event.widget, event))
        run.bind("<Button-3>", lambda event, slug=ref.slug: self._tile_menu(slug, event.widget, event))
        run.bind("<Control-Button-1>", lambda event, slug=ref.slug: self._tile_menu(slug, event.widget, event))
        return frame

    def select(self, slug: Optional[str]) -> None:
        self.selected = slug
        for key, tile in self.tiles.items():
            try:
                tile.configure(highlightbackground="#2f6fd0" if key == slug else "#ffffff")
            except tk.TclError:  # pragma: no cover
                pass

    def _tile_menu(self, slug: str, widget, event=None) -> str:
        self.select(slug)
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Ausfuehren", command=lambda: self.run_macro(slug))
        menu.add_command(label="Bearbeiten...", command=lambda: self.edit_macro(slug))
        menu.add_command(label="Schritte anhaengen (aufnehmen)", command=lambda: self.append_recording(slug))
        menu.add_separator()
        menu.add_command(label="Umbenennen...", command=lambda: self.rename_macro(slug))
        menu.add_command(label="Tastenkuerzel...", command=lambda: self.set_hotkey(slug))
        menu.add_command(label="Duplizieren", command=lambda: self.duplicate_macro(slug))
        menu.add_separator()
        menu.add_command(label="Nach vorne", command=lambda: self.move_macro(slug, -1))
        menu.add_command(label="Nach hinten", command=lambda: self.move_macro(slug, 1))
        menu.add_separator()
        menu.add_command(label="Exportieren...", command=lambda: self.export_macro(slug))
        menu.add_command(label="Loeschen", command=lambda: self.delete_macro(slug))
        if event is not None:
            menu.tk_popup(event.x_root, event.y_root)
        else:
            menu.tk_popup(widget.winfo_rootx() + 20, widget.winfo_rooty() + 20)
        return "break"

    # ------------------------------------------------------------------
    # Hilfsdienste
    # ------------------------------------------------------------------
    def _post(self, function: Callable[[], None]) -> None:
        """Aus Fremd-Threads sicher in den Oberflaechen-Thread wechseln."""
        self.ui_queue.put(function)

    def _pump(self) -> None:
        while True:
            try:
                function = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                function()
            except Exception as problem:  # pragma: no cover
                self.log(f"Fehler in der Oberflaeche: {problem}")
        self.root.after(60, self._pump)

    def log(self, message: str) -> None:
        self.log_widget.configure(state=tk.NORMAL)
        self.log_widget.insert(tk.END, f"{time.strftime('%H:%M:%S')}  {message}\n")
        self.log_widget.see(tk.END)
        self.log_widget.configure(state=tk.DISABLED)

    def set_status(self, message: str) -> None:
        self.status.set(message)

    @property
    def screen(self):
        if self._screen is None:
            self._screen = get_screen()
        return self._screen

    @property
    def inputs(self):
        if self._inputs is None:
            from .inputs import get_input_backend

            self._inputs = get_input_backend()
        return self._inputs

    def _check_permissions(self, always: bool = False) -> None:
        if not permissions.is_macos():
            if always:
                messagebox.showinfo(APP_NAME, "Freigaben sind nur unter macOS noetig.", parent=self.root)
            return
        gaps = permissions.missing()
        if not gaps:
            if always:
                messagebox.showinfo(APP_NAME, "Alle Freigaben sind erteilt.", parent=self.root)
            return
        message = "Es fehlen noch Freigaben: " + ", ".join(gaps) + "\n\n" + permissions.HINT
        if messagebox.askyesno(APP_NAME, message + "\n\nSystemeinstellungen jetzt oeffnen?", parent=self.root):
            if "Bedienungshilfen" in gaps:
                permissions.request_accessibility()
            if "Bildschirmaufnahme" in gaps:
                permissions.request_screen_recording()

    def _busy(self) -> bool:
        if self.recorder is not None:
            messagebox.showinfo(APP_NAME, "Es laeuft gerade eine Aufnahme.", parent=self.root)
            return True
        if self.player is not None and self.player.running:
            messagebox.showinfo(APP_NAME, "Es laeuft gerade eine Wiedergabe.", parent=self.root)
            return True
        return False

    def _require_selection(self) -> Optional[str]:
        if self.selected and self.store.macro_dir(self.selected).exists():
            return self.selected
        messagebox.showinfo(APP_NAME, "Bitte zuerst einen Button auswaehlen (einmal anklicken).",
                            parent=self.root)
        return None

    # ------------------------------------------------------------------
    # Aufnahme
    # ------------------------------------------------------------------
    def new_button(self) -> None:
        if self._busy():
            return
        name = simpledialog.askstring(APP_NAME, "Wie soll der Button heissen?", parent=self.root)
        if not name or not name.strip():
            return
        slug = self.store.create(name.strip())
        self.refresh()
        self.select(slug)
        self.start_recording(slug, append=False)

    def append_recording(self, slug: str) -> None:
        if self._busy():
            return
        self.start_recording(slug, append=True)

    def start_recording(self, slug: str, append: bool) -> None:
        if permissions.is_macos() and permissions.missing():
            self._check_permissions()
            return
        try:
            screen = self.screen
            backend = self.inputs
        except Exception as problem:
            messagebox.showerror(APP_NAME, f"Bildschirm/Eingabe nicht verfuegbar:\n{problem}",
                                 parent=self.root)
            return

        macro = self.store.load(slug)
        if not append:
            macro.steps = []
        self.recording_slug = slug
        self._recording_append = append
        self._recording_macro = macro

        factory = AnchorFactory(self.store, slug, self.config)
        buffer = ScreenBuffer(screen, fps=float(self.config.get("record_fps", 6.0)),
                              locator=backend.mouse_position)
        session = RecordingSession(
            anchor_maker=factory.make,
            frame_provider=buffer.frame_for,
            config=self.config,
            on_step=lambda step: self._post(lambda: self._on_recorded(step)),
        )
        self.recorder = Recorder(session, buffer=buffer)
        self._show_recording_hud(macro.name, len(macro.steps))
        self.stop_button.configure(state=tk.NORMAL)
        if bool(self.config.get("hide_window_on_record", True)):
            self.root.withdraw()
        self._countdown(int(self.config.get("countdown", 3)), self._really_start_recording)

    def _countdown(self, seconds: int, then: Callable[[], None]) -> None:
        if seconds <= 0:
            then()
            return
        self._hud_message(f"Start in {seconds} ...")
        self.root.after(1000, lambda: self._countdown(seconds - 1, then))

    def _really_start_recording(self) -> None:
        if self.recorder is None:
            return
        self._update_hud_ignore_region()
        try:
            self.recorder.start()
        except Exception as problem:
            self.recorder = None
            self._close_hud()
            self.root.deiconify()
            messagebox.showerror(APP_NAME, f"Aufnahme nicht moeglich:\n{problem}", parent=self.root)
            return
        self._hud_message("Aufnahme laeuft")
        self.hotkeys.set_bindings({self.config.get("stop_hotkey", "<f9>"): lambda: self._post(self.stop_recording)})
        self.set_status("Aufnahme laeuft ...")

    def _on_recorded(self, step) -> None:
        if self.recorder is None:
            return
        count = len(self.recorder.session.steps)
        self._hud_message("Aufnahme laeuft", f"{count} Schritte  -  zuletzt: {step.describe()}")

    def stop_recording(self, cancel: bool = False) -> None:
        recorder = self.recorder
        if recorder is None:
            return
        steps = recorder.stop()
        self.recorder = None
        self.hotkeys.set_bindings({})
        self._close_hud()
        self.stop_button.configure(state=tk.DISABLED)
        self.root.deiconify()
        self.root.lift()
        slug = self.recording_slug
        self.recording_slug = None
        if slug is None:
            return
        macro = self._recording_macro
        if cancel:
            if not self._recording_append:
                self.store.delete(slug)
            self.refresh()
            self.set_status("Aufnahme verworfen.")
            return
        macro.steps = list(macro.steps) + list(steps) if self._recording_append else list(steps)
        self.store.save(macro)
        self.store.prune_assets(macro)
        self.cache.clear()
        self.refresh()
        self.select(slug)
        self.set_status(f"{len(macro.steps)} Schritte aufgenommen.")
        self.log(f"'{macro.name}': {len(macro.steps)} Schritte gespeichert.")
        if macro.steps and messagebox.askyesno(
            APP_NAME, "Aufnahme gespeichert. Schritte jetzt durchsehen?", parent=self.root
        ):
            self.edit_macro(slug)

    # -- Aufnahmefenster -------------------------------------------------
    def _show_recording_hud(self, name: str, existing: int) -> None:
        hud = tk.Toplevel(self.root)
        hud.title("Aufnahme")
        hud.attributes("-topmost", True)
        hud.resizable(False, False)
        hud.protocol("WM_DELETE_WINDOW", lambda: self.stop_recording(cancel=True))
        frame = ttk.Frame(hud, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        self._hud_title = tk.StringVar(value=f"Aufnahme: {name}")
        self._hud_state = tk.StringVar(value="Start ...")
        self._hud_detail = tk.StringVar(value=f"{existing} Schritte" if existing else "")
        ttk.Label(frame, textvariable=self._hud_title, font=("Helvetica", 13, "bold")).pack(anchor="w")
        ttk.Label(frame, textvariable=self._hud_state, foreground="#c00000").pack(anchor="w")
        ttk.Label(frame, textvariable=self._hud_detail, wraplength=300).pack(anchor="w", pady=(2, 8))
        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X)
        stop_label = f"Fertig ({pretty(self.config.get('stop_hotkey', '<f9>'))})"
        ttk.Button(buttons, text=stop_label, command=self.stop_recording).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Verwerfen", command=lambda: self.stop_recording(cancel=True)).pack(side=tk.LEFT, padx=6)
        hud.update_idletasks()
        screen_width = hud.winfo_screenwidth()
        screen_height = hud.winfo_screenheight()
        hud.geometry(f"+{screen_width - hud.winfo_width() - 40}+{screen_height - hud.winfo_height() - 80}")
        self.recording_hud = hud

    def _hud_message(self, state: str, detail: Optional[str] = None) -> None:
        if self.recording_hud is None:
            return
        self._hud_state.set(state)
        if detail is not None:
            self._hud_detail.set(detail)

    def _update_hud_ignore_region(self) -> None:
        """Klicks auf das Aufnahmefenster selbst nicht mitschneiden."""
        if self.recording_hud is None or self.recorder is None:
            return
        hud = self.recording_hud
        hud.update_idletasks()
        margin = 12
        region = (
            hud.winfo_rootx() - margin,
            hud.winfo_rooty() - margin - 30,
            hud.winfo_width() + 2 * margin,
            hud.winfo_height() + 2 * margin + 30,
        )
        self.recorder.session.ignore_regions = [region]
        if self.recorder.running:
            self.root.after(700, self._update_hud_ignore_region)

    def _close_hud(self) -> None:
        if self.recording_hud is not None:
            try:
                self.recording_hud.destroy()
            except tk.TclError:  # pragma: no cover
                pass
            self.recording_hud = None

    # ------------------------------------------------------------------
    # Wiedergabe
    # ------------------------------------------------------------------
    def run_macro(self, slug: str, start_index: int = 0, only_one: bool = False) -> None:
        if self._busy():
            return
        self.select(slug)
        try:
            macro = self.store.load(slug)
        except OSError as problem:
            messagebox.showerror(APP_NAME, f"Button konnte nicht geladen werden:\n{problem}", parent=self.root)
            return
        if not macro.steps:
            messagebox.showinfo(APP_NAME, "Dieser Button enthaelt noch keine Schritte.", parent=self.root)
            return
        if permissions.is_macos() and permissions.missing():
            self._check_permissions()
            return
        try:
            screen, backend = self.screen, self.inputs
        except Exception as problem:
            messagebox.showerror(APP_NAME, f"Bildschirm/Eingabe nicht verfuegbar:\n{problem}", parent=self.root)
            return

        self.player = Player(screen, backend, self.store, self.config,
                             on_event=lambda event: self._post(lambda: self._on_playback(event)),
                             cache=self.cache)
        self.stop_button.configure(state=tk.NORMAL)
        self.set_status(f"'{macro.name}' laeuft ...")
        self.log(f"Start: {macro.name}")
        self.hotkeys.set_bindings({self.config.get("panic_hotkey", "<f10>"): lambda: self._post(self.stop_everything)})
        if bool(self.config.get("hide_window_on_run", True)):
            self.root.withdraw()

        def worker() -> None:
            time.sleep(0.4)
            result = self.player.run(macro, start_index=start_index, only_one=only_one)
            self._post(lambda: self._playback_finished(macro, result))

        self.player_thread = threading.Thread(target=worker, name="klickpilot-player", daemon=True)
        self.player_thread.start()

    def _on_playback(self, event) -> None:
        if event.kind == "step":
            self.set_status(event.message)
            self.log(event.message)
        elif event.kind == "warn":
            self.log("! " + event.message)
        elif event.kind == "error":
            self.log("!! " + event.message)

    def _playback_finished(self, macro: Macro, result) -> None:
        self.player = None
        self.player_thread = None
        self.hotkeys.set_bindings({})
        self.stop_button.configure(state=tk.DISABLED)
        self.root.deiconify()
        self.root.lift()
        self._apply_hotkeys()
        if result.ok:
            self.set_status(f"'{macro.name}' fertig ({result.done} Schritte).")
            self.log(f"Fertig: {macro.name}")
        else:
            self.set_status(f"'{macro.name}' abgebrochen: {result.message}")
            self.log(f"Abbruch: {result.message}")
            if result.failed_index is not None:
                messagebox.showwarning(
                    APP_NAME,
                    f"Der Ablauf wurde angehalten.\n\n{result.message}\n\n"
                    "Moegliche Ursachen: Das Fenster sieht heute anders aus, es ist "
                    "verdeckt, oder das Programm braucht laenger. Im Bearbeiten-Fenster "
                    "laesst sich der betroffene Schritt neu aufnehmen oder seine "
                    "Erkennungsschwelle senken.",
                    parent=self.root,
                )

    def stop_everything(self) -> None:
        if self.player is not None:
            self.player.stop()
            self.set_status("Wird angehalten ...")
        if self.recorder is not None:
            self.stop_recording()

    # ------------------------------------------------------------------
    # Verwaltung
    # ------------------------------------------------------------------
    def edit_selected(self) -> None:
        slug = self._require_selection()
        if slug:
            self.edit_macro(slug)

    def edit_macro(self, slug: str) -> None:
        if self._busy():
            return
        from .editor import StepEditor

        StepEditor(self.root, self, slug)

    def rename_selected(self) -> None:
        slug = self._require_selection()
        if slug:
            self.rename_macro(slug)

    def rename_macro(self, slug: str) -> None:
        macro = self.store.load(slug)
        name = simpledialog.askstring(APP_NAME, "Neuer Name:", initialvalue=macro.name, parent=self.root)
        if name and name.strip():
            self.store.rename(slug, name.strip())
            self.refresh()
            self.select(slug)

    def hotkey_selected(self) -> None:
        slug = self._require_selection()
        if slug:
            self.set_hotkey(slug)

    def set_hotkey(self, slug: str) -> None:
        macro = self.store.load(slug)
        current = pretty(normalize(macro.hotkey)) if macro.hotkey else ""
        value = simpledialog.askstring(
            APP_NAME,
            "Tastenkuerzel (z. B. cmd+shift+1 oder f6).\nLeer lassen = kein Kuerzel:",
            initialvalue=current, parent=self.root,
        )
        if value is None:
            return
        macro.hotkey = value.strip()
        self.store.save(macro)
        self.refresh()
        self.select(slug)

    def move_macro(self, slug: str, delta: int) -> None:
        """Verschiebt eine Kachel im Raster nach vorne oder hinten."""
        order = [ref.slug for ref in self.store.list_macros()]
        if slug not in order:
            return
        position = order.index(slug)
        target = max(0, min(len(order) - 1, position + delta))
        if target == position:
            return
        order.insert(target, order.pop(position))
        self.store.save_order(order)
        self.refresh()
        self.select(slug)

    def duplicate_selected(self) -> None:
        slug = self._require_selection()
        if slug:
            self.duplicate_macro(slug)

    def duplicate_macro(self, slug: str) -> None:
        new_slug = self.store.duplicate(slug)
        self.refresh()
        self.select(new_slug)

    def delete_selected(self) -> None:
        slug = self._require_selection()
        if slug:
            self.delete_macro(slug)

    def delete_macro(self, slug: str) -> None:
        macro = self.store.load(slug)
        if not messagebox.askyesno(APP_NAME, f"'{macro.name}' wirklich loeschen?", parent=self.root):
            return
        self.store.delete(slug)
        self.selected = None
        self.cache.clear()
        self.refresh()
        self.set_status(f"'{macro.name}' geloescht.")

    def export_selected(self) -> None:
        slug = self._require_selection()
        if slug:
            self.export_macro(slug)

    def export_macro(self, slug: str) -> None:
        macro = self.store.load(slug)
        target = filedialog.asksaveasfilename(
            parent=self.root, title="Button exportieren",
            initialfile=f"{slug}.klickpilot.zip", defaultextension=".zip",
            filetypes=[("Klickpilot-Button", "*.zip")],
        )
        if not target:
            return
        self.store.export_zip(slug, target)
        self.set_status(f"'{macro.name}' exportiert.")

    def import_macro(self) -> None:
        source = filedialog.askopenfilename(
            parent=self.root, title="Button importieren",
            filetypes=[("Klickpilot-Button", "*.zip"), ("Alle Dateien", "*.*")],
        )
        if not source:
            return
        try:
            slug = self.store.import_zip(source)
        except Exception as problem:
            messagebox.showerror(APP_NAME, f"Import fehlgeschlagen:\n{problem}", parent=self.root)
            return
        self.refresh()
        self.select(slug)
        self.set_status("Button importiert.")

    def open_data_folder(self) -> None:
        import subprocess

        path = str(self.store.root)
        try:
            subprocess.run(["open", path], check=False)
        except Exception:
            messagebox.showinfo(APP_NAME, f"Datenordner: {path}", parent=self.root)

    def show_help(self) -> None:
        messagebox.showinfo(
            APP_NAME,
            "So funktioniert Klickpilot:\n\n"
            "1. '+ Neuer Button' anklicken und einen Namen vergeben.\n"
            "2. Nach dem Countdown wird alles mitgeschnitten: Klicks, Doppelklicks,\n"
            "   Ziehen, Scrollen und Tastatureingaben.\n"
            f"3. Mit {pretty(self.config.get('stop_hotkey', '<f9>'))} beenden.\n"
            "4. Der neue Button spielt den Ablauf jederzeit wieder ab.\n\n"
            "Beim Abspielen wird nicht stumpf die alte Mausposition angefahren:\n"
            "Klickpilot merkt sich, wie die Stelle aussah, und sucht sie auf dem\n"
            "aktuellen Bildschirm wieder. Verschobene oder anders grosse Fenster\n"
            "sind damit kein Problem.\n\n"
            f"Notbremse waehrend der Wiedergabe: {pretty(self.config.get('panic_hotkey', '<f10>'))} "
            "oder die Esc-Taste im Klickpilot-Fenster.",
            parent=self.root,
        )

    # ------------------------------------------------------------------
    # Einstellungen und Kuerzel
    # ------------------------------------------------------------------
    def _apply_hotkeys(self) -> None:
        if self.recorder is not None or (self.player is not None and self.player.running):
            return
        bindings: Dict[str, Callable[[], None]] = {}
        for ref in self.store.list_macros():
            if ref.hotkey:
                bindings[ref.hotkey] = (lambda slug=ref.slug: self._post(lambda: self.run_macro(slug)))
        self.hotkeys.set_bindings(bindings)

    def open_settings(self) -> None:
        SettingsDialog(self.root, self)

    def apply_config(self, values: dict) -> None:
        self.config.update(values)
        save_config(self.config)
        self.store = Store(data_root(self.config))
        self.cache = TemplateCache(self.store)
        self.refresh()
        self.set_status("Einstellungen gespeichert.")

    def quit(self) -> None:
        if self.recorder is not None:
            self.stop_recording(cancel=True)
        if self.player is not None:
            self.player.stop()
        self.hotkeys.stop()
        self.root.destroy()


class SettingsDialog(tk.Toplevel):
    FIELDS = [
        ("data_root", "Datenordner", "text"),
        ("match_threshold", "Erkennungsschwelle (0.5 - 0.95)", "float"),
        ("anchor_timeout", "Wartezeit auf Bedienelemente (Sekunden)", "float"),
        ("max_delay", "Laengste uebernommene Pause (Sekunden)", "float"),
        ("speed", "Wiedergabetempo (1.0 = wie aufgenommen)", "float"),
        ("countdown", "Countdown vor Aufnahme/Wiedergabe (Sekunden)", "int"),
        ("record_fps", "Bildschirmfotos je Sekunde bei der Aufnahme", "float"),
        ("columns", "Buttons je Zeile", "int"),
        ("stop_hotkey", "Kuerzel zum Beenden der Aufnahme", "text"),
        ("panic_hotkey", "Notbremse waehrend der Wiedergabe", "text"),
    ]

    def __init__(self, parent: tk.Tk, app: KlickpilotApp):
        super().__init__(parent)
        self.app = app
        self.title("Einstellungen")
        self.transient(parent)
        self.resizable(False, False)
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)
        self.vars: Dict[str, tk.Variable] = {}
        for row, (key, label, _kind) in enumerate(self.FIELDS):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=3)
            variable = tk.StringVar(value=str(app.config.get(key, "")))
            self.vars[key] = variable
            ttk.Entry(frame, textvariable=variable, width=34).grid(row=row, column=1, sticky="ew", pady=3, padx=(10, 0))
        row = len(self.FIELDS)
        self.hide_record = tk.BooleanVar(value=bool(app.config.get("hide_window_on_record", True)))
        self.hide_run = tk.BooleanVar(value=bool(app.config.get("hide_window_on_run", True)))
        ttk.Checkbutton(frame, text="Fenster waehrend der Aufnahme ausblenden",
                        variable=self.hide_record).grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Checkbutton(frame, text="Fenster waehrend der Wiedergabe ausblenden",
                        variable=self.hide_run).grid(row=row + 1, column=0, columnspan=2, sticky="w")
        buttons = ttk.Frame(frame)
        buttons.grid(row=row + 2, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Abbrechen", command=self.destroy).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(buttons, text="Sichern", command=self.save).pack(side=tk.RIGHT)

    def save(self) -> None:
        values: dict = {}
        for key, label, kind in self.FIELDS:
            raw = self.vars[key].get().strip()
            try:
                if kind == "float":
                    values[key] = float(raw.replace(",", "."))
                elif kind == "int":
                    values[key] = int(float(raw))
                else:
                    values[key] = raw
            except ValueError:
                messagebox.showerror(APP_NAME, f"Ungueltiger Wert bei '{label}'.", parent=self)
                return
        values["match_threshold"] = min(0.98, max(0.4, float(values["match_threshold"])))
        values["hide_window_on_record"] = bool(self.hide_record.get())
        values["hide_window_on_run"] = bool(self.hide_run.get())
        self.app.apply_config(values)
        self.destroy()


def main() -> None:
    root = tk.Tk()
    KlickpilotApp(root)
    root.mainloop()


if __name__ == "__main__":  # pragma: no cover
    main()
