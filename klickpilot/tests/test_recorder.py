"""Prueft, dass aus rohen Ereignissen eine sinnvolle Schrittfolge wird."""
from __future__ import annotations

import pytest

from klickpilot.models import CLICK, DRAG, KEY, SCROLL, TEXT, Anchor
from klickpilot.recorder import RecordingSession


class StubFrame:
    def __init__(self, name="frame"):
        self.name = name


@pytest.fixture
def session(config):
    frames = [StubFrame()]
    made = []

    def frame_provider(point, not_before=None, **_kwargs):
        return frames[0]

    def anchor_maker(frame, point):
        made.append(point)
        return Anchor(template=f"a{len(made):04d}.png", size=(20, 20), hotspot=(10, 10), point=point)

    recording = RecordingSession(anchor_maker, frame_provider, config)
    recording.made_points = made
    return recording


def test_single_click_becomes_one_step(session):
    session.mouse_down(100.0, 400, 300)
    session.mouse_up(100.1, 400, 300)
    steps = session.finish()
    assert len(steps) == 1
    assert steps[0].kind == CLICK and steps[0].clicks == 1
    assert steps[0].anchor.point == (400, 300)


def test_two_quick_clicks_become_a_double_click(session):
    session.mouse_down(100.0, 400, 300)
    session.mouse_up(100.05, 400, 300)
    session.mouse_down(100.2, 402, 301)
    session.mouse_up(100.25, 402, 301)
    steps = session.finish()
    assert len(steps) == 1 and steps[0].clicks == 2
    # Fuer den zweiten Klick wurde kein zweiter Bildausschnitt angelegt.
    assert len(session.made_points) == 1


def test_slow_clicks_stay_separate(session):
    session.mouse_down(100.0, 400, 300)
    session.mouse_up(100.05, 400, 300)
    session.mouse_down(102.0, 400, 300)
    session.mouse_up(102.05, 400, 300)
    steps = session.finish()
    assert [step.clicks for step in steps] == [1, 1]
    assert steps[1].delay_before == pytest.approx(1.95, abs=0.01)


def test_clicks_at_different_places_stay_separate(session):
    session.mouse_down(100.0, 400, 300)
    session.mouse_up(100.05, 400, 300)
    session.mouse_down(100.2, 900, 300)
    session.mouse_up(100.25, 900, 300)
    assert len(session.finish()) == 2


def test_long_mouse_movement_becomes_a_drag(session):
    session.mouse_down(100.0, 400, 300)
    session.mouse_up(100.6, 800, 520)
    steps = session.finish()
    assert len(steps) == 1 and steps[0].kind == DRAG
    assert steps[0].anchor.point == (400, 300)
    assert steps[0].anchor_to.point == (800, 520)


def test_typing_is_collected_into_one_step(session):
    for index, character in enumerate("Hallo"):
        session.key_char(100.0 + index * 0.1, character)
    steps = session.finish()
    assert len(steps) == 1
    assert steps[0].kind == TEXT and steps[0].text == "Hallo"


def test_text_is_flushed_before_a_click(session):
    session.key_char(100.0, "a")
    session.key_char(100.1, "b")
    session.mouse_down(101.0, 10, 10)
    session.mouse_up(101.1, 10, 10)
    steps = session.finish()
    assert [step.kind for step in steps] == [TEXT, CLICK]
    assert steps[0].text == "ab"


def test_long_pause_splits_text(session):
    session.key_char(100.0, "a")
    session.key_char(105.0, "b")
    steps = session.finish()
    assert [step.text for step in steps] == ["a", "b"]


def test_special_key_ends_text_and_becomes_own_step(session):
    session.key_char(100.0, "x")
    session.key_special(100.4, "enter")
    steps = session.finish()
    assert [step.kind for step in steps] == [TEXT, KEY]
    assert steps[1].key == "enter"


def test_shortcut_keeps_its_modifiers(session):
    session.key_special(100.0, "c", ["cmd"])
    step = session.finish()[0]
    assert step.kind == KEY and step.key == "c" and step.modifiers == ["cmd"]


def test_scrolling_at_one_spot_is_summed_up(session):
    session.scroll(100.0, 500, 400, 0, -3)
    session.scroll(100.2, 500, 400, 0, -4)
    steps = session.finish()
    assert len(steps) == 1 and steps[0].kind == SCROLL
    assert steps[0].dy == -7


def test_clicks_on_the_recorder_window_are_ignored(session):
    session.ignore_regions = [(1000, 900, 300, 120)]
    session.mouse_down(100.0, 1100, 950)
    session.mouse_up(100.1, 1100, 950)
    assert session.finish() == []


def test_pauses_are_capped(session, config):
    config["max_delay"] = 2.0
    session.mouse_down(100.0, 10, 10)
    session.mouse_up(100.1, 10, 10)
    session.mouse_down(200.0, 500, 10)
    session.mouse_up(200.1, 500, 10)
    steps = session.finish()
    assert steps[1].delay_before == 2.0


def test_modifiers_are_carried_into_the_click(session):
    session.modifiers.add("shift")
    session.mouse_down(100.0, 10, 10)
    session.mouse_up(100.1, 10, 10)
    assert session.finish()[0].modifiers == ["shift"]


def test_reported_steps_reach_the_callback(config):
    seen = []
    recording = RecordingSession(
        lambda frame, point: Anchor(template="a.png", size=(4, 4), hotspot=(2, 2), point=point),
        lambda point, not_before=None: StubFrame(),
        config,
        on_step=seen.append,
    )
    recording.mouse_down(1.0, 5, 5)
    recording.mouse_up(1.1, 5, 5)
    recording.key_char(2.0, "z")
    recording.finish()
    assert [step.kind for step in seen] == [CLICK, TEXT]
