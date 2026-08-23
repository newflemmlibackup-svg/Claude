"""Globale Tastenkuerzel: Normalform, Anzeige und Abgleich gegen KeyEvents.

Der Abgleich laeuft ueber den eigenen Tastatur-Tap (keytap.py) statt ueber
pynputs GlobalHotKeys - Details siehe hotkeys.py.
"""
from __future__ import annotations

from klickpilot.hotkeys import HotkeyManager, _parse, normalize, pretty
from klickpilot.keytap import KeyEvent


def test_normalize_wraps_named_keys_and_keeps_digits_bare():
    assert normalize("f9") == "<f9>"
    assert normalize("cmd+shift+1") == "<cmd>+<shift>+1"
    assert normalize("Cmd + C") == "<cmd>+c"
    assert normalize("") == ""


def test_normalize_is_idempotent_on_already_normalized_strings():
    assert normalize("<cmd>+<shift>+1") == "<cmd>+<shift>+1"


def test_pretty_renders_a_readable_form():
    assert pretty("<cmd>+<shift>+1") == "Cmd+Shift+1"
    assert pretty("<f9>") == "F9"
    assert pretty("") == ""


def test_parse_splits_modifiers_from_the_key():
    assert _parse("<cmd>+<shift>+1") == (frozenset({"cmd", "shift"}), "1")
    assert _parse("<f9>") == (frozenset(), "f9")
    assert _parse("") is None


class FakeKeyTap:
    """Merkt sich die Callbacks, statt einen echten Quartz-Tap zu oeffnen."""

    def __init__(self):
        self.on_down = None
        self.on_up = None
        self.stopped = False

    def start(self, on_down, on_up):
        self.on_down = on_down
        self.on_up = on_up

    def stop(self):
        self.stopped = True


def test_hotkey_fires_on_exact_modifier_match(monkeypatch):
    import klickpilot.hotkeys as hotkeys_module

    tap = FakeKeyTap()
    monkeypatch.setattr(hotkeys_module, "create_key_tap", lambda: tap)
    fired = []
    manager = HotkeyManager()
    manager.set_bindings({"cmd+shift+1": lambda: fired.append("go")})

    tap.on_down(KeyEvent(18, "1", "1", frozenset({"cmd", "shift"})))
    assert fired == ["go"]


def test_hotkey_does_not_fire_with_extra_modifiers_held(monkeypatch):
    import klickpilot.hotkeys as hotkeys_module

    tap = FakeKeyTap()
    monkeypatch.setattr(hotkeys_module, "create_key_tap", lambda: tap)
    fired = []
    manager = HotkeyManager()
    manager.set_bindings({"f9": lambda: fired.append("stop")})

    tap.on_down(KeyEvent(101, "f9", None, frozenset({"cmd"})))
    assert fired == []
    tap.on_down(KeyEvent(101, "f9", None, frozenset()))
    assert fired == ["stop"]


def test_hotkey_ignores_the_shifted_symbol_and_matches_by_keycode(monkeypatch):
    """cmd+shift+1 soll ueber die physische '1'-Taste feuern, auch wenn das
    tatsaechlich getippte Zeichen unter Shift z. B. '!' waere."""
    import klickpilot.hotkeys as hotkeys_module

    tap = FakeKeyTap()
    monkeypatch.setattr(hotkeys_module, "create_key_tap", lambda: tap)
    fired = []
    manager = HotkeyManager()
    manager.set_bindings({"cmd+shift+1": lambda: fired.append("go")})

    # name bleibt "1" (positionsbezogen), char waere hier "!" - wird ignoriert.
    tap.on_down(KeyEvent(18, "1", "!", frozenset({"cmd", "shift"})))
    assert fired == ["go"]


def test_rebinding_replaces_the_previous_hotkeys(monkeypatch):
    import klickpilot.hotkeys as hotkeys_module

    taps = []
    monkeypatch.setattr(hotkeys_module, "create_key_tap", lambda: taps.append(FakeKeyTap()) or taps[-1])
    fired = []
    manager = HotkeyManager()
    manager.set_bindings({"f9": lambda: fired.append("old")})
    manager.set_bindings({"f10": lambda: fired.append("new")})

    assert taps[0].stopped is True
    taps[1].on_down(KeyEvent(101, "f9", None, frozenset()))
    assert fired == []
    taps[1].on_down(KeyEvent(109, "f10", None, frozenset()))
    assert fired == ["new"]


def test_empty_bindings_never_open_a_tap(monkeypatch):
    import klickpilot.hotkeys as hotkeys_module

    monkeypatch.setattr(hotkeys_module, "create_key_tap",
                        lambda: (_ for _ in ()).throw(AssertionError("sollte nicht aufgerufen werden")))
    manager = HotkeyManager()
    manager.set_bindings({})
    manager.stop()


def test_stop_clears_bindings(monkeypatch):
    import klickpilot.hotkeys as hotkeys_module

    tap = FakeKeyTap()
    monkeypatch.setattr(hotkeys_module, "create_key_tap", lambda: tap)
    manager = HotkeyManager()
    manager.set_bindings({"f9": lambda: None})
    manager.stop()
    assert tap.stopped is True
    assert manager.bindings == {}
