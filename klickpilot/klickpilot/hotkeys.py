"""Globale Tastenkuerzel (laufen auch, wenn Klickpilot im Hintergrund ist).

Nutzt denselben eigenen Tastatur-Tap wie die Aufnahme (:mod:`klickpilot.keytap`)
statt pynputs ``GlobalHotKeys`` - der haette dasselbe Absturzrisiko wie
pynputs normaler Tastatur-Listener (siehe keytap.py). Aufnahme und
Tastenkuerzel laufen unabhaengig voneinander und oeffnen deshalb je einen
eigenen Tap.

Der Abgleich erfolgt bewusst ueber den positionsbezogenen Tastencode
(``KeyEvent.name``), nicht ueber das getippte Zeichen: Bei einem Kuerzel wie
"cmd+shift+1" liefert die Taste unter gehaltener Shift-Taste je nach Layout
ein ganz anderes Zeichen (z. B. "!" statt "1") - der Tastencode bleibt
dagegen unabhaengig vom Layout und von gehaltenen Modifikatoren immer
derselbe.
"""
from __future__ import annotations

import threading
from typing import Callable, Dict, FrozenSet, List, Optional, Tuple

from .keytap import KeyEvent, create_key_tap
from .keytap import MODIFIER_NAMES as TAP_MODIFIER_NAMES

MODIFIER_ALIASES = {
    "cmd": "<cmd>", "command": "<cmd>", "meta": "<cmd>",
    "ctrl": "<ctrl>", "control": "<ctrl>",
    "alt": "<alt>", "option": "<alt>", "opt": "<alt>",
    "shift": "<shift>",
}

_MODIFIER_TOKENS = {"cmd", "ctrl", "alt", "shift"}


def normalize(hotkey: str) -> str:
    """Wandelt 'cmd+shift+1' in die Normalform '<cmd>+<shift>+1'."""
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


def _parse(normalized: str) -> Optional[Tuple[FrozenSet[str], str]]:
    """'<cmd>+<shift>+1' -> (frozenset({'cmd', 'shift'}), '1')."""
    if not normalized:
        return None
    modifiers = set()
    key = None
    for token in normalized.split("+"):
        bare = token.strip("<>")
        if bare in _MODIFIER_TOKENS:
            modifiers.add(bare)
        elif bare:
            key = bare
    if key is None:
        return None
    return frozenset(modifiers), key


class HotkeyManager:
    """Meldet eine Menge globaler Kuerzel an; bei Aenderung neu registrieren."""

    def __init__(self):
        self._tap = None
        self._lock = threading.Lock()
        self.bindings: Dict[str, Callable[[], None]] = {}
        self._parsed: List[Tuple[FrozenSet[str], str, Callable[[], None]]] = []
        self.error: Optional[str] = None

    def set_bindings(self, bindings: Dict[str, Callable[[], None]]) -> None:
        with self._lock:
            self.bindings = {normalize(key): value for key, value in bindings.items() if key}
            self._parsed = []
            for hotkey, callback in self.bindings.items():
                parsed = _parse(hotkey)
                if parsed is not None:
                    modifiers, key_name = parsed
                    self._parsed.append((modifiers, key_name, callback))
            self._restart()

    def _restart(self) -> None:
        self._stop_tap()
        if not self._parsed:
            return
        try:
            self._tap = create_key_tap()
            self._tap.start(self._on_key_down, self._on_key_up)
            self.error = None
        except Exception as problem:
            self._tap = None
            self.error = str(problem)

    def _on_key_down(self, event: KeyEvent) -> None:
        if event.name in TAP_MODIFIER_NAMES:
            return
        for modifiers, key_name, callback in self._parsed:
            if event.modifiers == modifiers and event.name == key_name:
                try:
                    callback()
                except Exception:
                    pass
                return

    def _on_key_up(self, event: KeyEvent) -> None:
        pass

    def _stop_tap(self) -> None:
        if self._tap is not None:
            try:
                self._tap.stop()
            except Exception:
                pass
            self._tap = None

    def stop(self) -> None:
        with self._lock:
            self.bindings = {}
            self._parsed = []
            self._stop_tap()
