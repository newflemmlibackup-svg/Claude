"""Datenmodell: Beschreibungen und JSON-Umwandlung."""
from __future__ import annotations

from klickpilot.models import (
    CLICK, DRAG, KEY, SCROLL, TEXT, WAIT, WAIT_IMAGE, Anchor, Macro, Step,
)


def test_describe_is_understandable():
    assert Step(kind=CLICK).describe() == "Klick (links)"
    assert Step(kind=CLICK, clicks=2).describe() == "Doppelklick (links)"
    assert Step(kind=CLICK, button="right").describe() == "Klick (rechts)"
    assert "Cmd" not in Step(kind=KEY, key="c", modifiers=["cmd"]).describe()
    assert Step(kind=KEY, key="c", modifiers=["cmd"]).describe() == "Taste: cmd+c"
    assert Step(kind=TEXT, text="Hallo").describe() == 'Text eingeben: "Hallo"'
    assert Step(kind=DRAG).describe().startswith("Ziehen")
    assert Step(kind=SCROLL, dy=-4).describe().startswith("Scrollen runter")
    assert Step(kind=WAIT, seconds=1.5).describe() == "Warten: 1.5 s"
    assert Step(kind=WAIT_IMAGE, mode="vanish").describe().endswith("verschwindet")


def test_long_text_is_shortened_in_the_description():
    description = Step(kind=TEXT, text="x" * 80).describe()
    assert len(description) < 60 and description.endswith('..."')


def test_step_round_trip_keeps_everything():
    step = Step(
        kind=CLICK, delay_before=1.25, clicks=3, button="right", modifiers=["cmd"],
        anchor=Anchor(template="a.png", size=(4, 6), hotspot=(2, 3), point=(9, 8), scale=2.0),
        timeout=12.5, on_error="skip", enabled=False, note="Hinweis",
    )
    copy = Step.from_dict(step.to_dict())
    assert copy == step


def test_macro_round_trip_and_asset_list():
    macro = Macro(
        name="Test",
        steps=[Step(kind=CLICK, anchor=Anchor(template="a.png", context="a_ctx.png")),
               Step(kind=TEXT, text="hallo")],
        speed=2.0, repeat=4, hotkey="f5",
    )
    copy = Macro.from_dict(macro.to_dict(), slug="test")
    assert copy.name == "Test" and copy.speed == 2.0 and copy.repeat == 4
    assert copy.hotkey == "f5" and len(copy.steps) == 2
    assert sorted(copy.asset_names()) == ["a.png", "a_ctx.png"]


def test_defaults_survive_broken_input():
    step = Step.from_dict({"kind": CLICK, "clicks": "2", "timeout": ""})
    assert step.clicks == 2 and step.timeout is None
    anchor = Anchor.from_dict({"template": "a.png", "size": None, "hotspot": "x"})
    assert anchor.size == (0, 0) and anchor.hotspot == (0.0, 0.0)


def test_uses_anchor_flag():
    assert Step(kind=CLICK).uses_anchor
    assert Step(kind=SCROLL).uses_anchor
    assert not Step(kind=TEXT).uses_anchor
    assert not Step(kind=WAIT).uses_anchor
