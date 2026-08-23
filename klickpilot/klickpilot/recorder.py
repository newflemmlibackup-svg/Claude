"""Aufnahme: mitschneiden, was der Anwender mit Maus und Tastatur tut.

Die eigentliche Auswertung steckt in :class:`RecordingSession` und kommt
ohne macOS-Bibliotheken aus (dadurch testbar). :class:`Recorder` haengt
lediglich die Systemereignisse (pynput) und den Bildschirmpuffer daran.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, List, Optional, Sequence, Tuple

from .models import (
    CLICK, DRAG, KEY, SCROLL, TEXT, WAIT, Anchor, Step,
)

# Ab dieser Strecke (in Punkten) gilt eine Mausbewegung mit gedrueckter
# Taste als Ziehen und nicht mehr als Klick.
DRAG_DISTANCE = 12.0
# Innerhalb dieser Zeit und Entfernung wird aus zwei Klicks ein Doppelklick.
DOUBLE_CLICK_TIME = 0.5
DOUBLE_CLICK_DISTANCE = 8.0
# Nach so langer Tippppause wird der gesammelte Text zu einem Schritt.
TEXT_IDLE = 1.5

TEXT_MODIFIERS = {"shift", "fn"}


def _distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


class RecordingSession:
    """Formt aus einzelnen Ereignissen eine saubere Schrittfolge."""

    def __init__(self, anchor_maker: Callable[[object, Tuple[float, float]], Anchor],
                 frame_provider: Callable[..., object], config: dict,
                 on_step: Optional[Callable[[Step], None]] = None):
        self.anchor_maker = anchor_maker
        self.frame_provider = frame_provider
        self.config = config
        self.on_step = on_step
        self.steps: List[Step] = []
        self.ignore_regions: List[Tuple[float, float, float, float]] = []
        self.modifiers: set = set()
        self._press: Optional[dict] = None
        self._last_event_time: Optional[float] = None
        self._text_buffer: List[str] = []
        self._text_start: Optional[float] = None
        self._text_last: Optional[float] = None
        self._last_click: Optional[dict] = None

    # -- Hilfen ----------------------------------------------------------
    def ignored(self, point: Tuple[float, float]) -> bool:
        for x, y, width, height in self.ignore_regions:
            if x <= point[0] <= x + width and y <= point[1] <= y + height:
                return True
        return False

    def _delay(self, moment: float) -> float:
        if self._last_event_time is None:
            return 0.0
        maximum = float(self.config.get("max_delay", 3.0))
        return round(max(0.0, min(maximum, moment - self._last_event_time)), 2)

    def _add(self, step: Step, moment: float) -> Step:
        self.steps.append(step)
        self._last_event_time = moment
        if self.on_step is not None:
            self.on_step(step)
        return step

    def _make_anchor(self, moment: float, point: Tuple[float, float]) -> Optional[Anchor]:
        frame = self.frame_provider(point, not_before=self._last_event_time)
        if frame is None:
            return None
        return self.anchor_maker(frame, point)

    # -- Maus ------------------------------------------------------------
    def mouse_down(self, moment: float, x: float, y: float, button: str = "left") -> None:
        point = (x, y)
        if self.ignored(point):
            self._press = None
            return
        self._flush_text(moment)
        # Foto vor dem Klick sichern - danach kann der Dialog schon weg sein.
        frame = self.frame_provider(point, not_before=self._last_event_time)
        self._press = {"time": moment, "point": point, "button": button, "frame": frame,
                       "modifiers": sorted(self.modifiers)}

    def mouse_up(self, moment: float, x: float, y: float, button: str = "left") -> Optional[Step]:
        press = self._press
        self._press = None
        if press is None or press["button"] != button:
            return None
        point = (x, y)
        if self.ignored(point) or press["frame"] is None:
            return None
        travelled = _distance(press["point"], point)

        if travelled >= DRAG_DISTANCE:
            step = Step(
                kind=DRAG,
                delay_before=self._delay(press["time"]),
                anchor=self.anchor_maker(press["frame"], press["point"]),
                anchor_to=self.anchor_maker(press["frame"], point),
                button=button,
                modifiers=press["modifiers"],
            )
            self._last_click = None
            return self._add(step, moment)

        # Mehrfachklick an gleicher Stelle zusammenfassen.
        previous = self._last_click
        if (
            previous is not None
            and self.steps
            and self.steps[-1].kind == CLICK
            and self.steps[-1].button == button
            and moment - previous["time"] <= DOUBLE_CLICK_TIME
            and _distance(previous["point"], press["point"]) <= DOUBLE_CLICK_DISTANCE
        ):
            self.steps[-1].clicks += 1
            previous["time"] = moment
            self._last_event_time = moment
            if self.on_step is not None:
                self.on_step(self.steps[-1])
            return self.steps[-1]

        step = Step(
            kind=CLICK,
            delay_before=self._delay(press["time"]),
            anchor=self.anchor_maker(press["frame"], press["point"]),
            button=button,
            clicks=1,
            modifiers=[m for m in press["modifiers"] if m != "fn"],
        )
        self._last_click = {"time": moment, "point": press["point"]}
        return self._add(step, moment)

    def scroll(self, moment: float, x: float, y: float, dx: float, dy: float) -> Optional[Step]:
        point = (x, y)
        if self.ignored(point):
            return None
        self._flush_text(moment)
        # Aufeinanderfolgendes Scrollen an gleicher Stelle aufsummieren.
        if (
            self.steps
            and self.steps[-1].kind == SCROLL
            and self._last_event_time is not None
            and moment - self._last_event_time < 0.6
        ):
            self.steps[-1].dx += dx
            self.steps[-1].dy += dy
            self._last_event_time = moment
            if self.on_step is not None:
                self.on_step(self.steps[-1])
            return self.steps[-1]
        anchor = self._make_anchor(moment, point)
        if anchor is None:
            return None
        step = Step(kind=SCROLL, delay_before=self._delay(moment), anchor=anchor, dx=dx, dy=dy)
        self._last_click = None
        return self._add(step, moment)

    # -- Tastatur --------------------------------------------------------
    def key_char(self, moment: float, character: str) -> None:
        if self._text_last is not None and moment - self._text_last > TEXT_IDLE:
            self._flush_text(moment)
        if not self._text_buffer:
            self._text_start = moment
        self._text_buffer.append(character)
        self._text_last = moment
        self._last_click = None

    def key_special(self, moment: float, name: str,
                    modifiers: Optional[Sequence[str]] = None) -> Step:
        self._flush_text(moment)
        step = Step(
            kind=KEY,
            delay_before=self._delay(moment),
            key=name,
            modifiers=sorted(set(modifiers or [])),
        )
        self._last_click = None
        return self._add(step, moment)

    def _flush_text(self, moment: Optional[float] = None) -> Optional[Step]:
        if not self._text_buffer:
            return None
        text = "".join(self._text_buffer)
        start = self._text_start if self._text_start is not None else (moment or 0.0)
        self._text_buffer = []
        self._text_start = None
        step = Step(kind=TEXT, delay_before=self._delay(start), text=text)
        result = self._add(step, self._text_last or start)
        self._text_last = None
        return result

    def add_wait(self, seconds: float) -> Step:
        step = Step(kind=WAIT, seconds=float(seconds))
        self.steps.append(step)
        if self.on_step is not None:
            self.on_step(step)
        return step

    def finish(self) -> List[Step]:
        self._flush_text()
        self._press = None
        return self.steps


# Umsetzung der pynput-Tastennamen auf die Namen in :mod:`inputs`.
SPECIAL_KEYS = {
    "enter": "enter", "tab": "tab", "backspace": "backspace", "delete": "forward_delete",
    "esc": "escape", "up": "up", "down": "down", "left": "left", "right": "right",
    "home": "home", "end": "end", "page_up": "page_up", "page_down": "page_down",
}
for _number in range(1, 20):
    SPECIAL_KEYS[f"f{_number}"] = f"f{_number}"

MODIFIER_KEYS = {
    "cmd": "cmd", "cmd_l": "cmd", "cmd_r": "cmd",
    "shift": "shift", "shift_l": "shift", "shift_r": "shift",
    "alt": "alt", "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
}


class Recorder:
    """Verbindet die Systemereignisse mit einer :class:`RecordingSession`."""

    def __init__(self, session: RecordingSession, buffer=None,
                 on_stop: Optional[Callable[[], None]] = None):
        self.session = session
        self.buffer = buffer
        self.on_stop = on_stop
        self._mouse_listener = None
        self._keyboard_listener = None
        self._lock = threading.Lock()
        self.running = False
        self.started_at = 0.0

    def start(self) -> None:
        from pynput import keyboard, mouse

        if self.buffer is not None:
            self.buffer.start()
        self.started_at = time.time()
        self.running = True
        self._mouse_listener = mouse.Listener(
            on_click=self._on_click, on_scroll=self._on_scroll
        )
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._mouse_listener.start()
        self._keyboard_listener.start()

    def stop(self) -> List[Step]:
        self.running = False
        for listener in (self._mouse_listener, self._keyboard_listener):
            if listener is not None:
                listener.stop()
        self._mouse_listener = None
        self._keyboard_listener = None
        if self.buffer is not None:
            self.buffer.stop()
        steps = self.session.finish()
        if self.on_stop is not None:
            self.on_stop()
        return steps

    # -- Ereignisse ------------------------------------------------------
    def _on_click(self, x, y, button, pressed) -> None:
        if not self.running:
            return
        name = getattr(button, "name", "left")
        name = {"left": "left", "right": "right", "middle": "middle"}.get(name, "left")
        with self._lock:
            try:
                if pressed:
                    self.session.mouse_down(time.time(), x, y, name)
                else:
                    self.session.mouse_up(time.time(), x, y, name)
            except Exception:
                pass

    def _on_scroll(self, x, y, dx, dy) -> None:
        if not self.running:
            return
        with self._lock:
            try:
                self.session.scroll(time.time(), x, y, dx, dy)
            except Exception:
                pass

    def _on_press(self, key) -> None:
        if not self.running:
            return
        with self._lock:
            self._handle_key(key)

    def _on_release(self, key) -> None:
        if not self.running:
            return
        name = getattr(key, "name", None)
        if name in MODIFIER_KEYS:
            self.session.modifiers.discard(MODIFIER_KEYS[name])

    def _handle_key(self, key) -> None:
        moment = time.time()
        name = getattr(key, "name", None)
        character = getattr(key, "char", None)

        if name in MODIFIER_KEYS:
            self.session.modifiers.add(MODIFIER_KEYS[name])
            return
        if name == "space":
            character = " "
            name = None
        held = {m for m in self.session.modifiers if m not in TEXT_MODIFIERS}

        if name in SPECIAL_KEYS:
            self.session.key_special(moment, SPECIAL_KEYS[name], sorted(self.session.modifiers))
            return
        if character is None:
            return
        if held:
            # Kurzbefehl wie Cmd+C - nicht als Text mitschreiben.
            self.session.key_special(moment, character.lower(), sorted(self.session.modifiers))
            return
        try:
            self.session.key_char(moment, character)
        except Exception:
            pass
