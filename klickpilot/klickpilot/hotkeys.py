"""Globale Tastenkuerzel (laufen auch, wenn Klickpilot im Hintergrund ist)."""
from __future__ import annotations

import threading
from typing import Callable, Dict, Optional

MODIFIER_ALIASES = {
    "cmd": "<cmd>", "command": "<cmd>", "meta": "<cmd>",
    "ctrl": "<ctrl>", "control": "<ctrl>",
    "alt": "<alt>", "option": "<alt>", "opt": "<alt>",
    "shift": "<shift>",
}


def normalize(hotkey: str) -> str:
    """Wandelt 'cmd+shift+1' in die pynput-Schreibweise '<cmd>+<shift>+1'."""
    hotkey = (hotkey or "").strip().lower()
    if not hotkey:
        return ""
    parts = []
    for token in hotkey.replace(" ", "").split("+"):
        if not token:
            continue
        if token in MODIFIER_ALIASES:
            parts.append(MODIFIER_ALIASES[token])
        elif token.startswith("<") and token.endswith(">"):
            parts.append(token)
        elif len(token) > 1:
            parts.append(f"<{token}>")
        else:
            parts.append(token)
    return "+".join(parts)


def pretty(hotkey: str) -> str:
    """Anzeigeform, z. B. '<cmd>+<shift>+1' -> 'Cmd+Shift+1'."""
    if not hotkey:
        return ""
    labels = {"cmd": "Cmd", "ctrl": "Ctrl", "alt": "Alt", "shift": "Shift"}
    parts = []
    for token in hotkey.split("+"):
        token = token.strip("<>")
        parts.append(labels.get(token, token.upper() if len(token) == 1 else token.capitalize()))
    return "+".join(parts)


class HotkeyManager:
    """Meldet eine Menge globaler Kuerzel an; bei Aenderung neu registrieren."""

    def __init__(self):
        self._listener = None
        self._lock = threading.Lock()
        self.bindings: Dict[str, Callable[[], None]] = {}
        self.error: Optional[str] = None

    def set_bindings(self, bindings: Dict[str, Callable[[], None]]) -> None:
        with self._lock:
            self.bindings = {normalize(key): value for key, value in bindings.items() if key}
            self._restart()

    def _restart(self) -> None:
        self._stop_listener()
        if not self.bindings:
            return
        try:
            from pynput import keyboard

            self._listener = keyboard.GlobalHotKeys(dict(self.bindings))
            self._listener.daemon = True
            self._listener.start()
            self.error = None
        except Exception as problem:
            self._listener = None
            self.error = str(problem)

    def _stop_listener(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

    def stop(self) -> None:
        with self._lock:
            self.bindings = {}
            self._stop_listener()
