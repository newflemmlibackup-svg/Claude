"""Erzeugen von Maus- und Tastaturereignissen unter macOS (CoreGraphics).

Die Ereignisse werden auf Systemebene eingespeist, deshalb funktionieren sie
auch bei Programmen ganz ohne Schnittstelle - genau wie ein echter
Mausklick. Voraussetzung ist die Freigabe unter
'Datenschutz & Sicherheit > Bedienungshilfen'.
"""
from __future__ import annotations

import time
from typing import Iterable, List, Optional, Sequence, Tuple

# Tastencodes des US-Layouts (ANSI). macOS adressiert Tasten ueber die
# physische Position, nicht ueber das Zeichen - fuer Kurzbefehle wie Cmd+C
# ist deshalb diese Tabelle noetig. Reiner Text wird stattdessen als
# Unicode gesendet und ist damit layoutunabhaengig.
KEY_CODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
    "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25, "7": 26,
    "-": 27, "8": 28, "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35,
    "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45,
    "m": 46, ".": 47, "`": 50,
    "enter": 36, "return": 36, "tab": 48, "space": 49, "backspace": 51, "delete": 51,
    "escape": 53, "esc": 53,
    "keypad_enter": 76, "keypad_plus": 69, "keypad_minus": 78, "keypad_multiply": 67,
    "keypad_divide": 75, "keypad_decimal": 65, "keypad_equals": 81, "keypad_clear": 71,
    "keypad_0": 82, "keypad_1": 83, "keypad_2": 84, "keypad_3": 85, "keypad_4": 86,
    "keypad_5": 87, "keypad_6": 88, "keypad_7": 89, "keypad_8": 91, "keypad_9": 92,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100,
    "f9": 101, "f10": 109, "f11": 103, "f12": 111, "f13": 105, "f14": 107, "f15": 113,
    "f16": 106, "f17": 64, "f18": 79, "f19": 80,
    "help": 114, "home": 115, "page_up": 116, "forward_delete": 117, "end": 119,
    "page_down": 121, "left": 123, "right": 124, "down": 125, "up": 126,
}

MODIFIER_LABELS = {
    "cmd": "Cmd", "shift": "Shift", "alt": "Alt", "ctrl": "Ctrl", "fn": "Fn",
}


class InputBackend:
    """Schnittstelle fuer Eingabesimulation (fuer Tests austauschbar)."""

    def mouse_position(self) -> Tuple[float, float]:  # pragma: no cover
        raise NotImplementedError

    def move(self, x: float, y: float) -> None:  # pragma: no cover
        raise NotImplementedError

    def click(self, x: float, y: float, button: str = "left", clicks: int = 1,
              modifiers: Sequence[str] = ()) -> None:  # pragma: no cover
        raise NotImplementedError

    def drag(self, x1: float, y1: float, x2: float, y2: float,
             button: str = "left") -> None:  # pragma: no cover
        raise NotImplementedError

    def scroll(self, x: float, y: float, dx: float, dy: float) -> None:  # pragma: no cover
        raise NotImplementedError

    def type_text(self, text: str, delay: float = 0.012) -> None:  # pragma: no cover
        raise NotImplementedError

    def key(self, name: str, modifiers: Sequence[str] = ()) -> None:  # pragma: no cover
        raise NotImplementedError


class QuartzInput(InputBackend):
    def __init__(self):
        import Quartz

        self.q = Quartz
        self._flags = {
            "cmd": Quartz.kCGEventFlagMaskCommand,
            "shift": Quartz.kCGEventFlagMaskShift,
            "alt": Quartz.kCGEventFlagMaskAlternate,
            "ctrl": Quartz.kCGEventFlagMaskControl,
            "fn": Quartz.kCGEventFlagMaskSecondaryFn,
        }
        self._buttons = {
            "left": (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp,
                     Quartz.kCGEventLeftMouseDragged, Quartz.kCGMouseButtonLeft),
            "right": (Quartz.kCGEventRightMouseDown, Quartz.kCGEventRightMouseUp,
                      Quartz.kCGEventRightMouseDragged, Quartz.kCGMouseButtonRight),
            "middle": (Quartz.kCGEventOtherMouseDown, Quartz.kCGEventOtherMouseUp,
                       Quartz.kCGEventOtherMouseDragged, Quartz.kCGMouseButtonCenter),
        }

    # -- Hilfsfunktionen ------------------------------------------------
    def _mask(self, modifiers: Sequence[str]) -> int:
        mask = 0
        for name in modifiers:
            mask |= self._flags.get(str(name).lower(), 0)
        return mask

    def _post(self, event, modifiers: Sequence[str] = ()) -> None:
        if modifiers:
            self.q.CGEventSetFlags(event, self._mask(modifiers))
        self.q.CGEventPost(self.q.kCGHIDEventTap, event)

    def _mouse_event(self, kind, x, y, button_const, click_state: int = 1):
        event = self.q.CGEventCreateMouseEvent(None, kind, (float(x), float(y)), button_const)
        if click_state > 1:
            self.q.CGEventSetIntegerValueField(event, self.q.kCGMouseEventClickState, int(click_state))
        return event

    # -- Maus -----------------------------------------------------------
    def mouse_position(self) -> Tuple[float, float]:
        event = self.q.CGEventCreate(None)
        location = self.q.CGEventGetLocation(event)
        return (float(location.x), float(location.y))

    def move(self, x: float, y: float, smooth: bool = True) -> None:
        if not smooth:
            self._post(self._mouse_event(self.q.kCGEventMouseMoved, x, y, self.q.kCGMouseButtonLeft))
            return
        start_x, start_y = self.mouse_position()
        distance = max(abs(x - start_x), abs(y - start_y))
        steps = int(min(28, max(1, distance / 24)))
        for index in range(1, steps + 1):
            ratio = index / steps
            eased = ratio * ratio * (3 - 2 * ratio)  # weiches Ein-/Ausschwingen
            self._post(self._mouse_event(
                self.q.kCGEventMouseMoved,
                start_x + (x - start_x) * eased,
                start_y + (y - start_y) * eased,
                self.q.kCGMouseButtonLeft,
            ))
            time.sleep(0.004)

    def click(self, x: float, y: float, button: str = "left", clicks: int = 1,
              modifiers: Sequence[str] = ()) -> None:
        down, up, _drag, const = self._buttons.get(button, self._buttons["left"])
        self.move(x, y)
        time.sleep(0.03)
        for index in range(max(1, int(clicks))):
            self._post(self._mouse_event(down, x, y, const, index + 1), modifiers)
            time.sleep(0.02)
            self._post(self._mouse_event(up, x, y, const, index + 1), modifiers)
            if index + 1 < clicks:
                time.sleep(0.06)

    def drag(self, x1: float, y1: float, x2: float, y2: float, button: str = "left") -> None:
        down, up, dragged, const = self._buttons.get(button, self._buttons["left"])
        self.move(x1, y1)
        time.sleep(0.05)
        self._post(self._mouse_event(down, x1, y1, const))
        time.sleep(0.08)
        steps = 24
        for index in range(1, steps + 1):
            ratio = index / steps
            eased = ratio * ratio * (3 - 2 * ratio)
            self._post(self._mouse_event(
                dragged, x1 + (x2 - x1) * eased, y1 + (y2 - y1) * eased, const
            ))
            time.sleep(0.012)
        time.sleep(0.08)
        self._post(self._mouse_event(up, x2, y2, const))

    def scroll(self, x: float, y: float, dx: float, dy: float) -> None:
        self.move(x, y)
        time.sleep(0.02)
        remaining_y, remaining_x = int(dy), int(dx)
        while remaining_y or remaining_x:
            chunk_y = max(-10, min(10, remaining_y))
            chunk_x = max(-10, min(10, remaining_x))
            event = self.q.CGEventCreateScrollWheelEvent(
                None, self.q.kCGScrollEventUnitLine, 2, chunk_y, chunk_x
            )
            self.q.CGEventPost(self.q.kCGHIDEventTap, event)
            remaining_y -= chunk_y
            remaining_x -= chunk_x
            time.sleep(0.03)

    # -- Tastatur -------------------------------------------------------
    def type_text(self, text: str, delay: float = 0.012) -> None:
        for character in text:
            if character == "\n":
                self.key("enter")
                continue
            if character == "\t":
                self.key("tab")
                continue
            for pressed in (True, False):
                event = self.q.CGEventCreateKeyboardEvent(None, 0, pressed)
                self.q.CGEventKeyboardSetUnicodeString(event, len(character), character)
                self.q.CGEventPost(self.q.kCGHIDEventTap, event)
                time.sleep(delay / 2)

    def key(self, name: str, modifiers: Sequence[str] = ()) -> None:
        code = KEY_CODES.get(str(name).lower())
        if code is None:
            if len(str(name)) == 1 and not modifiers:
                self.type_text(str(name))
                return
            raise ValueError(f"Unbekannte Taste: {name}")
        mask = self._mask(modifiers)
        for pressed in (True, False):
            event = self.q.CGEventCreateKeyboardEvent(None, code, pressed)
            if mask:
                self.q.CGEventSetFlags(event, mask)
            self.q.CGEventPost(self.q.kCGHIDEventTap, event)
            time.sleep(0.02)


_BACKEND: Optional[InputBackend] = None


def get_input_backend() -> InputBackend:
    global _BACKEND
    if _BACKEND is None:
        try:
            _BACKEND = QuartzInput()
        except ImportError as problem:
            raise RuntimeError(
                "Die macOS-Anbindung fehlt (Paket 'pyobjc-framework-Quartz'). "
                "Bitte 'pip install -r requirements.txt' auf einem Mac ausfuehren."
            ) from problem
    return _BACKEND


def set_input_backend(backend: Optional[InputBackend]) -> None:
    """Nur fuer Tests: Backend austauschen."""
    global _BACKEND
    _BACKEND = backend


def describe_key(name: str, modifiers: Iterable[str] = ()) -> str:
    parts: List[str] = [MODIFIER_LABELS.get(str(m).lower(), str(m)) for m in modifiers]
    parts.append(str(name).capitalize() if len(str(name)) > 1 else str(name).upper())
    return "+".join(parts)
