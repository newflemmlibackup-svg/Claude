"""Wiedergabe: findet der Player die Elemente und klickt er richtig?"""
from __future__ import annotations

import threading
import time

import pytest

from klickpilot.anchors import AnchorFactory
from klickpilot.models import (
    CLICK, KEY, ON_ERROR_RETRY, ON_ERROR_SKIP, TEXT, WAIT, WAIT_IMAGE, Macro, Step,
)
from klickpilot.player import Player
from klickpilot.screen import Frame

from .conftest import FakeScreen


def build_macro(store, config, ui, rows=(1,), origin=(300, 200)):
    slug = store.create("Ablauf")
    frame = Frame(ui.render(origin), (0.0, 0.0), 2.0, 1)
    factory = AnchorFactory(store, slug, config)
    steps = []
    for row in rows:
        pixel = ui.button_center(row, origin)
        anchor = factory.make(frame, (pixel[0] / 2, pixel[1] / 2))
        steps.append(Step(kind=CLICK, anchor=anchor))
    macro = Macro(name="Ablauf", steps=steps, slug=slug)
    store.save(macro)
    return macro


def test_click_follows_the_moved_window(store, config, ui, inputs):
    macro = build_macro(store, config, ui, rows=(1,))
    screen = FakeScreen(ui.render((1150, 720)))
    result = Player(screen, inputs, store, config).run(macro)
    assert result.ok and result.done == 1
    kind, x, y, button, clicks, _modifiers = inputs.actions[0]
    expected = ui.button_center(1, (1150, 720))
    assert kind == "click" and button == "left" and clicks == 1
    assert x * 2 == pytest.approx(expected[0], abs=3)
    assert y * 2 == pytest.approx(expected[1], abs=3)


def test_all_step_kinds_are_executed_in_order(store, config, ui, inputs):
    macro = build_macro(store, config, ui, rows=(0,))
    macro.steps.append(Step(kind=TEXT, text="Mueller"))
    macro.steps.append(Step(kind=KEY, key="enter"))
    macro.steps.append(Step(kind=WAIT, seconds=0.01))
    result = Player(FakeScreen(ui.render()), inputs, store, config).run(macro)
    assert result.ok
    assert [action[0] for action in inputs.actions] == ["click", "text", "key"]
    assert inputs.actions[1] == ("text", "Mueller")
    assert inputs.actions[2] == ("key", "enter", ())


def test_missing_element_stops_the_run(store, config, ui, inputs):
    macro = build_macro(store, config, ui, rows=(1,))
    macro.steps.append(Step(kind=TEXT, text="darf nicht mehr kommen"))
    result = Player(FakeScreen(ui.background.copy()), inputs, store, config).run(macro)
    assert not result.ok
    assert result.failed_index == 0
    assert "nicht gefunden" in result.message
    assert inputs.actions == []


def test_step_can_be_skipped_on_failure(store, config, ui, inputs):
    macro = build_macro(store, config, ui, rows=(1,))
    macro.steps[0].on_error = ON_ERROR_SKIP
    macro.steps.append(Step(kind=TEXT, text="weiter"))
    result = Player(FakeScreen(ui.background.copy()), inputs, store, config).run(macro)
    assert result.ok
    assert inputs.actions == [("text", "weiter")]


def test_retry_tries_again_before_giving_up(store, config, ui, inputs):
    macro = build_macro(store, config, ui, rows=(1,))
    macro.steps[0].on_error = ON_ERROR_RETRY
    macro.steps[0].timeout = 0.05
    screen = FakeScreen(ui.background.copy())
    events = []
    result = Player(screen, inputs, store, config, on_event=events.append).run(macro)
    assert not result.ok
    assert sum(1 for event in events if event.kind == "warn") >= 1
    assert screen.captures >= 3


def test_element_appearing_later_is_awaited(store, config, ui, inputs):
    macro = build_macro(store, config, ui, rows=(1,))
    macro.steps[0].timeout = 5.0
    screen = FakeScreen(ui.background.copy())

    def show_window_later():
        time.sleep(0.6)
        screen.show(ui.render((700, 500)))

    threading.Thread(target=show_window_later, daemon=True).start()
    result = Player(screen, inputs, store, config).run(macro)
    assert result.ok
    assert inputs.actions and inputs.actions[0][0] == "click"


def test_wait_image_vanish(store, config, ui, inputs):
    macro = build_macro(store, config, ui, rows=(1,))
    macro.steps[0].kind = WAIT_IMAGE
    macro.steps[0].mode = "vanish"
    macro.steps[0].timeout = 0.2
    result = Player(FakeScreen(ui.render()), inputs, store, config).run(macro)
    assert not result.ok and "nicht verschwunden" in result.message


def test_disabled_steps_are_left_out(store, config, ui, inputs):
    macro = build_macro(store, config, ui, rows=(0, 1))
    macro.steps[0].enabled = False
    result = Player(FakeScreen(ui.render()), inputs, store, config).run(macro)
    assert result.ok and len(inputs.actions) == 1


def test_repeat_runs_the_whole_sequence_again(store, config, ui, inputs):
    macro = build_macro(store, config, ui, rows=(0,))
    macro.repeat = 3
    Player(FakeScreen(ui.render()), inputs, store, config).run(macro)
    assert len(inputs.actions) == 3


def test_run_from_a_later_step_only(store, config, ui, inputs):
    macro = build_macro(store, config, ui, rows=(0, 1, 2))
    Player(FakeScreen(ui.render()), inputs, store, config).run(macro, start_index=2, only_one=True)
    expected = ui.button_center(2)
    assert len(inputs.actions) == 1
    assert inputs.actions[0][1] * 2 == pytest.approx(expected[0], abs=3)


def test_stop_interrupts_the_run(store, config, ui, inputs):
    macro = build_macro(store, config, ui, rows=(0,))
    macro.steps.insert(0, Step(kind=WAIT, seconds=5.0))
    player = Player(FakeScreen(ui.render()), inputs, store, config)
    threading.Thread(target=lambda: (time.sleep(0.2), player.stop()), daemon=True).start()
    started = time.time()
    result = player.run(macro)
    assert not result.ok and result.message == "Abgebrochen."
    assert time.time() - started < 2.0
    assert inputs.actions == []


def test_delays_are_shortened_by_the_speed_setting(store, config, ui, inputs):
    macro = build_macro(store, config, ui, rows=(0,))
    macro.steps[0].delay_before = 1.0
    macro.speed = 10.0
    started = time.time()
    Player(FakeScreen(ui.render()), inputs, store, config).run(macro)
    assert time.time() - started < 0.8
