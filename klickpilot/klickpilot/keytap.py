"""Eigene Tastaturerfassung fuer macOS (CoreGraphics/Quartz).

Ersetzt pynputs Tastatur-Listener. Der fragt bei jedem Tastendruck ueber
rohe ``ctypes``-Aufrufe das aktuelle Tastaturlayout bei Carbon/HIToolbox ab
(``TISCopyCurrentKeyboardInputSource`` / ``TSMGetInputSourceProperty``), und
zwar auf seinem eigenen Hintergrundthread. Ab macOS 26 verlangt das
Betriebssystem, dass dieser Aufruf ausschliesslich auf dem Hauptthread
laeuft, und beendet den Prozess sofort (SIGTRAP,
``dispatch_assert_queue_fail``), wenn er - wie bei pynput - von einem
anderen Thread aus kommt.

Dieser Tap liest das getippte Zeichen stattdessen direkt aus dem Ereignis
selbst (``CGEventKeyboardGetUnicodeString``): Das ist bereits vom
Betriebssystem uebersetzt und braucht keine eigene Layout-Abfrage - und ist
deshalb von jedem Thread aus gefahrlos aufrufbar. Fuer benannte Tasten
(Pfeile, Funktionstasten, Enter, ...) wird stattdessen der rein
positionsbezogene Tastencode ausgewertet, ueber dieselbe Tabelle wie in
:mod:`klickpilot.inputs` fuer die Wiedergabe - Aufnahme und Wiedergabe
sprechen damit dieselbe Namensvokabel.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Dict, FrozenSet, Optional

from .inputs import KEY_CODES

# Kehrt KEY_CODES (Name -> Tastencode) um, sodass sich ein erfasster
# Tastencode wieder einem Namen zuordnen laesst. macOS' Tastencodes sind an
# die physische Position gebunden, nicht an das Tastaturlayout - die
# Zuordnung stimmt deshalb unabhaengig vom eingestellten Layout und ist
# insbesondere fuer Tastenkuerzel robuster als das (layoutabhaengige)
# getippte Zeichen.
CODE_TO_NAME: Dict[int, str] = {}
for _name, _code in KEY_CODES.items():
    CODE_TO_NAME.setdefault(_code, _name)
# Mehrdeutige Codes (mehrere Namen in KEY_CODES) auf einen kanonischen Namen
# festlegen.
CODE_TO_NAME[36] = "enter"
CODE_TO_NAME[51] = "backspace"
CODE_TO_NAME[53] = "escape"

# Tasten ohne sinnvolles Zeichen - werden ausschliesslich ueber den Namen
# behandelt, selbst wenn ihr Unicode-Ergebnis zufaellig nicht leer ist (z. B.
# Tab/Enter/Escape liefern Steuerzeichen).
NAMED_KEYS = {"enter", "tab", "escape", "backspace", "forward_delete",
              "home", "end", "page_up", "page_down", "up", "down", "left", "right"}
NAMED_KEYS |= {f"f{_n}" for _n in range(1, 20)}

MODIFIER_NAMES = ("cmd", "shift", "alt", "ctrl", "fn")


@dataclass(frozen=True)
class KeyEvent:
    keycode: int
    name: Optional[str]        # positionsbezogener Name, z. B. "f9", "a" - None bei Sondertasten ohne Zuordnung
    char: Optional[str]        # getipptes Zeichen (layoutabhaengig uebersetzt), nur bei Tastendruck
    modifiers: FrozenSet[str]  # zu diesem Zeitpunkt gehaltene Modifikatoren


class KeyTap:
    """Schnittstelle fuer Tastaturerfassung (fuer Tests austauschbar)."""

    def start(self, on_down: Callable[[KeyEvent], None],
              on_up: Callable[[KeyEvent], None]) -> None:  # pragma: no cover
        raise NotImplementedError

    def stop(self) -> None:  # pragma: no cover
        raise NotImplementedError


class QuartzKeyTap(KeyTap):
    """Ein CGEventTap in einem eigenen Thread mit eigenem CFRunLoop."""

    def __init__(self):
        import Quartz  # Importfehler = Backend nicht verfuegbar

        self._quartz = Quartz
        self._thread: Optional[threading.Thread] = None
        self._run_loop = None
        self._tap = None
        self._on_down: Optional[Callable[[KeyEvent], None]] = None
        self._on_up: Optional[Callable[[KeyEvent], None]] = None
        self._held_modifiers: set = set()
        self._ready = threading.Event()
        self._error: Optional[str] = None

    def start(self, on_down: Callable[[KeyEvent], None],
              on_up: Callable[[KeyEvent], None]) -> None:
        self._on_down = on_down
        self._on_up = on_up
        self._held_modifiers = set()
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, name="klickpilot-keytap", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=3.0):
            raise RuntimeError("Tastaturerfassung konnte nicht gestartet werden (Zeitueberschreitung).")
        if self._error:
            raise RuntimeError(self._error)

    def stop(self) -> None:
        run_loop = self._run_loop
        if run_loop is not None:
            # CFRunLoopStop ist ausdruecklich dafuer vorgesehen, von einem
            # anderen Thread aus aufgerufen zu werden.
            self._quartz.CFRunLoopStop(run_loop)
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None
        self._run_loop = None
        self._tap = None

    # -- Läuft im eigenen Thread -----------------------------------------
    def _run(self) -> None:
        quartz = self._quartz
        mask = (
            quartz.CGEventMaskBit(quartz.kCGEventKeyDown)
            | quartz.CGEventMaskBit(quartz.kCGEventKeyUp)
            | quartz.CGEventMaskBit(quartz.kCGEventFlagsChanged)
        )
        tap = quartz.CGEventTapCreate(
            quartz.kCGSessionEventTap,
            quartz.kCGHeadInsertEventTap,
            quartz.kCGEventTapOptionListenOnly,
            mask,
            self._callback,
            None,
        )
        if tap is None:
            self._error = (
                "Tastaturerfassung nicht moeglich. Bitte in den Systemeinstellungen "
                "unter 'Datenschutz & Sicherheit > Bedienungshilfen' die Freigabe erteilen."
            )
            self._ready.set()
            return
        self._tap = tap
        source = quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        self._run_loop = quartz.CFRunLoopGetCurrent()
        quartz.CFRunLoopAddSource(self._run_loop, source, quartz.kCFRunLoopCommonModes)
        quartz.CGEventTapEnable(tap, True)
        self._ready.set()
        quartz.CFRunLoopRun()

    def _callback(self, proxy, event_type, event, refcon):
        quartz = self._quartz
        try:
            keycode = int(quartz.CGEventGetIntegerValueField(event, quartz.kCGKeyboardEventKeycode))
            if event_type == quartz.kCGEventFlagsChanged:
                flags = quartz.CGEventGetFlags(event)
                self._handle_modifier_change(keycode, flags)
                return event

            name = CODE_TO_NAME.get(keycode)
            if event_type == quartz.kCGEventKeyDown:
                char = self._unicode_string(event)
                if self._on_down:
                    self._on_down(KeyEvent(keycode, name, char, frozenset(self._held_modifiers)))
            elif event_type == quartz.kCGEventKeyUp:
                if self._on_up:
                    self._on_up(KeyEvent(keycode, name, None, frozenset(self._held_modifiers)))
        except Exception:
            pass
        return event

    def _handle_modifier_change(self, keycode: int, flags) -> None:
        active = self._modifiers_from_flags(flags)
        newly_pressed = active - self._held_modifiers
        newly_released = self._held_modifiers - active
        self._held_modifiers = active
        for label in newly_pressed:
            if self._on_down:
                self._on_down(KeyEvent(keycode, label, None, frozenset(self._held_modifiers)))
        for label in newly_released:
            if self._on_up:
                self._on_up(KeyEvent(keycode, label, None, frozenset(self._held_modifiers)))

    def _modifiers_from_flags(self, flags) -> set:
        quartz = self._quartz
        table = (
            (quartz.kCGEventFlagMaskCommand, "cmd"),
            (quartz.kCGEventFlagMaskShift, "shift"),
            (quartz.kCGEventFlagMaskAlternate, "alt"),
            (quartz.kCGEventFlagMaskControl, "ctrl"),
            (quartz.kCGEventFlagMaskSecondaryFn, "fn"),
        )
        return {label for bit, label in table if flags & bit}

    def _unicode_string(self, event) -> Optional[str]:
        quartz = self._quartz
        try:
            length, chars = quartz.CGEventKeyboardGetUnicodeString(event, 8, None, None)
        except Exception:
            return None
        if not length:
            return None
        try:
            text = "".join(chr(int(value)) for value in chars[:length])
        except Exception:
            return None
        return text or None


def create_key_tap() -> KeyTap:
    """Neue Tap-Instanz. Kein Singleton: Aufnahme und globale Kuerzel
    laufen gleichzeitig und brauchen je einen eigenen, unabhaengigen Tap."""
    try:
        return QuartzKeyTap()
    except ImportError as problem:
        raise RuntimeError(
            "Die macOS-Anbindung fehlt (Paket 'pyobjc-framework-Quartz'). "
            "Bitte 'pip install -r requirements.txt' auf einem Mac ausfuehren."
        ) from problem
