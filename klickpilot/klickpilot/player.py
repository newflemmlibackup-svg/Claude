"""Wiedergabe einer aufgenommenen Schrittfolge.

Vor jedem Klick wird die zugehoerige Schablone auf dem *aktuellen*
Bildschirm gesucht. Erst wenn sie gefunden ist, wird geklickt - dadurch
laufen Ablaeufe auch dann korrekt, wenn Fenster verschoben, anders gross
oder erst nach einer Wartezeit da sind.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .anchors import AnchorLocator, AnchorNotFound, TemplateCache
from .inputs import InputBackend
from .models import (
    CLICK, DRAG, KEY, ON_ERROR_RETRY, ON_ERROR_SKIP, SCROLL, TEXT, WAIT,
    WAIT_IMAGE, Macro, Step,
)
from .screen import ScreenSource
from .storage import Store

RETRY_LIMIT = 2


@dataclass
class PlaybackEvent:
    kind: str            # "step" | "info" | "warn" | "error" | "done"
    message: str
    index: int = 0
    total: int = 0
    score: Optional[float] = None


@dataclass
class PlaybackResult:
    ok: bool
    done: int = 0
    total: int = 0
    message: str = ""
    failed_index: Optional[int] = None
    events: List[PlaybackEvent] = field(default_factory=list)


class PlaybackAborted(RuntimeError):
    pass


class Player:
    def __init__(self, screen: ScreenSource, inputs: InputBackend, store: Store,
                 config: dict, on_event: Optional[Callable[[PlaybackEvent], None]] = None,
                 cache: Optional[TemplateCache] = None):
        self.screen = screen
        self.inputs = inputs
        self.store = store
        self.config = config
        self.on_event = on_event
        self.locator = AnchorLocator(screen, store, config, cache=cache)
        self._stop = threading.Event()
        self.running = False

    # -- Steuerung -------------------------------------------------------
    def stop(self) -> None:
        self._stop.set()

    def should_stop(self) -> bool:
        return self._stop.is_set()

    def _sleep(self, seconds: float) -> None:
        """Wartet, bleibt dabei aber auf den Abbruchwunsch ansprechbar."""
        deadline = time.time() + max(0.0, seconds)
        while time.time() < deadline:
            if self.should_stop():
                raise PlaybackAborted("Abgebrochen.")
            time.sleep(min(0.05, max(0.0, deadline - time.time())))
        if self.should_stop():
            raise PlaybackAborted("Abgebrochen.")

    def _emit(self, kind: str, message: str, index: int = 0, total: int = 0,
              score: Optional[float] = None) -> PlaybackEvent:
        event = PlaybackEvent(kind, message, index, total, score)
        if self.on_event is not None:
            try:
                self.on_event(event)
            except Exception:
                pass
        return event

    # -- Ablauf ----------------------------------------------------------
    def run(self, macro: Macro, start_index: int = 0, only_one: bool = False) -> PlaybackResult:
        self._stop.clear()
        self.running = True
        events: List[PlaybackEvent] = []
        steps = macro.steps[start_index:start_index + 1] if only_one else macro.steps[start_index:]
        total = len(steps)
        speed = max(0.1, float(macro.speed or self.config.get("speed", 1.0) or 1.0))
        done = 0
        try:
            passes = 1 if only_one else max(1, int(macro.repeat or 1))
            for cycle in range(passes):
                if passes > 1:
                    events.append(self._emit("info", f"Durchlauf {cycle + 1} von {passes}", 0, total))
                for offset, step in enumerate(steps):
                    index = start_index + offset
                    if not step.enabled:
                        continue
                    events.append(
                        self._emit("step", f"{index + 1}. {step.describe()}", index + 1, total)
                    )
                    outcome = self._run_step(macro, step, index, total, speed, events)
                    if outcome == "abort":
                        return PlaybackResult(False, done, total, events[-1].message, index, events)
                    done += 1
            events.append(self._emit("done", "Fertig."))
            return PlaybackResult(True, done, total, "Fertig.", None, events)
        except PlaybackAborted:
            events.append(self._emit("warn", "Abgebrochen."))
            return PlaybackResult(False, done, total, "Abgebrochen.", None, events)
        finally:
            self.running = False

    def _run_step(self, macro: Macro, step: Step, index: int, total: int,
                  speed: float, events: List[PlaybackEvent]) -> str:
        attempts = RETRY_LIMIT + 1 if step.on_error == ON_ERROR_RETRY else 1
        for attempt in range(attempts):
            try:
                self._sleep(step.delay_before / speed)
                self._perform(macro, step)
                return "ok"
            except PlaybackAborted:
                raise
            except AnchorNotFound as error:
                message = f"Schritt {index + 1} ({step.describe()}): {error}"
                if attempt + 1 < attempts:
                    events.append(self._emit("warn", message + " - neuer Versuch", index + 1, total))
                    continue
            except Exception as error:  # pragma: no cover - unerwartete Faelle
                message = f"Schritt {index + 1} ({step.describe()}): {error}"
                if attempt + 1 < attempts:
                    events.append(self._emit("warn", message + " - neuer Versuch", index + 1, total))
                    continue
            if step.on_error == ON_ERROR_SKIP:
                events.append(self._emit("warn", message + " - uebersprungen", index + 1, total))
                return "skip"
            events.append(self._emit("error", message, index + 1, total))
            return "abort"
        return "ok"

    def _locate(self, macro: Macro, step: Step, anchor) -> tuple:
        located = self.locator.locate(
            macro.slug, anchor, timeout=step.timeout, should_stop=self.should_stop
        )
        if self.should_stop():
            raise PlaybackAborted("Abgebrochen.")
        return located.point, located.score

    def _perform(self, macro: Macro, step: Step) -> None:
        settle = float(self.config.get("settle_after_click", 0.25))

        if step.kind == CLICK:
            (x, y), score = self._locate(macro, step, step.anchor)
            self._emit("info", f"gefunden ({score:.0%})", score=score)
            self.inputs.click(x, y, step.button, step.clicks, step.modifiers)
            self._sleep(settle)
            return

        if step.kind == DRAG:
            (x1, y1), _ = self._locate(macro, step, step.anchor)
            if step.anchor_to is not None:
                (x2, y2), _ = self._locate(macro, step, step.anchor_to)
            else:
                x2, y2 = x1, y1
            self.inputs.drag(x1, y1, x2, y2, step.button)
            self._sleep(settle)
            return

        if step.kind == SCROLL:
            (x, y), _ = self._locate(macro, step, step.anchor)
            self.inputs.scroll(x, y, step.dx, step.dy)
            self._sleep(settle)
            return

        if step.kind == TEXT:
            self.inputs.type_text(step.text)
            return

        if step.kind == KEY:
            self.inputs.key(step.key, step.modifiers)
            return

        if step.kind == WAIT:
            self._sleep(step.seconds)
            return

        if step.kind == WAIT_IMAGE:
            if step.mode == "appear":
                self._locate(macro, step, step.anchor)
            else:
                gone = self.locator.wait_until_gone(
                    macro.slug, step.anchor, timeout=step.timeout,
                    should_stop=self.should_stop,
                )
                if self.should_stop():
                    raise PlaybackAborted("Abgebrochen.")
                if not gone:
                    raise AnchorNotFound("Das Element ist nicht verschwunden.")
            return

        raise ValueError(f"Unbekannter Schritt: {step.kind}")
