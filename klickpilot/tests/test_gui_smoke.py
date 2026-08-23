"""Oberflaeche: laesst sich alles oeffnen und bedienen, ohne zu brechen?

Diese Tests brauchen eine Anzeige. Ohne Tkinter bzw. ohne Display werden
sie uebersprungen.
"""
from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")
pytest.importorskip("PIL.ImageTk")

from klickpilot.models import CLICK, TEXT, Anchor, Step  # noqa: E402


@pytest.fixture
def root():
    try:
        window = tk.Tk()
    except tk.TclError as problem:  # pragma: no cover - kein Display
        pytest.skip(f"keine Anzeige verfuegbar: {problem}")
    window.withdraw()
    yield window
    try:
        window.destroy()
    except tk.TclError:
        pass


@pytest.fixture
def app(root, tmp_path, monkeypatch):
    from klickpilot import app as app_module
    from klickpilot.config import DEFAULT_CONFIG

    settings = dict(DEFAULT_CONFIG)
    settings["data_root"] = str(tmp_path / "buttons")
    settings["anchor_timeout"] = 0.2
    monkeypatch.setattr(app_module, "load_config", lambda: dict(settings))
    monkeypatch.setattr(app_module, "save_config", lambda values: None)
    instance = app_module.KlickpilotApp(root)
    yield instance
    instance.hotkeys.stop()


def add_macro(app, name="Rechnung drucken", steps=2):
    import numpy as np

    slug = app.store.create(name)
    image = (np.random.default_rng(0).random((30, 40, 3)) * 255).astype(np.uint8)
    app.store.store_asset(slug, image, "a0001.png")
    macro = app.store.load(slug)
    macro.steps = [
        Step(kind=CLICK, anchor=Anchor(template="a0001.png", size=(40, 30), hotspot=(20, 15))),
        Step(kind=TEXT, text="Hallo"),
    ][:steps]
    app.store.save(macro)
    return slug


def select_row(editor, index):
    """Waehlt eine Zeile so aus, wie es ein Mausklick tun wuerde."""
    editor.listbox.selection_clear(0, tk.END)
    editor.listbox.selection_set(index)
    editor._on_select()


def test_window_starts_empty_with_a_hint(app):
    app.refresh()
    texts = [child.cget("text") for child in app.grid_frame.winfo_children()
             if child.winfo_class() == "TLabel"]
    assert any("Noch keine Buttons" in text for text in texts)


def test_macro_shows_up_as_a_tile(app):
    slug = add_macro(app)
    app.refresh()
    assert slug in app.tiles
    app.select(slug)
    assert app.selected == slug


def test_status_and_log_can_be_written(app):
    app.set_status("Test laeuft")
    app.log("Eine Meldung")
    assert app.status.get() == "Test laeuft"
    assert "Eine Meldung" in app.log_widget.get("1.0", tk.END)


def test_ui_queue_runs_work_in_the_main_thread(app):
    marks = []
    app._post(lambda: marks.append(1))
    app._pump()
    assert marks == [1]


def test_settings_dialog_saves_values(app, root):
    from klickpilot.app import SettingsDialog

    dialog = SettingsDialog(root, app)
    dialog.vars["match_threshold"].set("0,85")
    dialog.vars["columns"].set("4")
    dialog.save()
    assert app.config["match_threshold"] == pytest.approx(0.85)
    assert app.config["columns"] == 4


def test_settings_dialog_refuses_nonsense(app, root, monkeypatch):
    from klickpilot import app as app_module
    from klickpilot.app import SettingsDialog

    shown = []
    monkeypatch.setattr(app_module.messagebox, "showerror", lambda *a, **k: shown.append(a))
    dialog = SettingsDialog(root, app)
    dialog.vars["columns"].set("viele")
    dialog.save()
    assert shown, "es haette eine Fehlermeldung kommen muessen"


def test_step_editor_lists_and_edits_steps(app, root):
    from klickpilot.editor import StepEditor

    slug = add_macro(app)
    app.refresh()
    editor = StepEditor(root, app, slug)
    assert editor.listbox.size() == 2
    assert "Klick" in editor.listbox.get(0)

    select_row(editor, 1)
    editor.move_up()
    assert "Text" in editor.listbox.get(0)

    editor.toggle_enabled()
    assert editor.macro.steps[0].enabled is False

    editor.delete_step()
    assert editor.listbox.size() == 1

    editor.insert_wait()
    assert editor.listbox.size() == 2
    assert "Warten" in editor.listbox.get(1)

    editor.save_and_close()
    assert len(app.store.load(slug).steps) == 2


def test_step_editor_shows_the_saved_screenshot(app, root):
    from klickpilot.editor import StepEditor

    slug = add_macro(app)
    editor = StepEditor(root, app, slug)
    select_row(editor, 0)
    assert editor._preview_image is not None
    assert "Klickpunkt" in editor.preview_hint.cget("text")
    editor.close()


def test_step_editor_writes_back_the_fields(app, root):
    from klickpilot.editor import StepEditor

    slug = add_macro(app)
    editor = StepEditor(root, app, slug)
    select_row(editor, 0)
    editor.delay_var.set("2.5")
    editor.threshold_var.set("0.6")
    editor.note_var.set("Speichern-Knopf")
    editor.name_var.set("Neuer Name")
    editor.save_and_close()

    macro = app.store.load(slug)
    assert macro.name == "Neuer Name"
    assert macro.steps[0].delay_before == pytest.approx(2.5)
    assert macro.steps[0].anchor.threshold == pytest.approx(0.6)
    assert macro.steps[0].note == "Speichern-Knopf"


def test_running_without_steps_is_refused(app, monkeypatch):
    from klickpilot import app as app_module

    shown = []
    monkeypatch.setattr(app_module.messagebox, "showinfo", lambda *a, **k: shown.append(a))
    slug = app.store.create("Leer")
    app.refresh()
    app.run_macro(slug)
    assert shown and "keine Schritte" in shown[0][1]


def test_delete_asks_first(app, monkeypatch):
    from klickpilot import app as app_module

    slug = add_macro(app)
    app.refresh()
    monkeypatch.setattr(app_module.messagebox, "askyesno", lambda *a, **k: False)
    app.delete_macro(slug)
    assert app.store.macro_dir(slug).exists()
    monkeypatch.setattr(app_module.messagebox, "askyesno", lambda *a, **k: True)
    app.delete_macro(slug)
    assert not app.store.macro_dir(slug).exists()


def test_export_and_import_round_trip_through_the_ui(app, tmp_path, monkeypatch):
    from klickpilot import app as app_module

    slug = add_macro(app, "Zum Teilen")
    app.refresh()
    target = tmp_path / "geteilt.zip"
    monkeypatch.setattr(app_module.filedialog, "asksaveasfilename", lambda **k: str(target))
    app.export_macro(slug)
    assert target.exists()

    monkeypatch.setattr(app_module.filedialog, "askopenfilename", lambda **k: str(target))
    app.import_macro()
    assert len(app.store.list_macros()) == 2


class FakeRecorder:
    """Ersetzt den echten Rekorder: ohne pynput, dafuer von Hand fuetterbar."""

    def __init__(self, session, buffer=None, on_stop=None):
        self.session = session
        self.buffer = buffer
        self.on_stop = on_stop
        self.running = False

    def start(self):
        self.running = True

    def stop(self):
        self.running = False
        return self.session.finish()


@pytest.fixture
def recording_app(app, monkeypatch, ui):
    """App mit simuliertem Bildschirm, simulierter Maus und Fake-Rekorder."""
    from klickpilot import app as app_module

    from .conftest import FakeInput, FakeScreen

    app._screen = FakeScreen(ui.render((300, 200)))
    app._inputs = FakeInput()
    app.config["countdown"] = 0
    app.config["hide_window_on_record"] = False
    app.config["hide_window_on_run"] = False
    app.config["anchor_timeout"] = 1.0
    monkeypatch.setattr(app_module, "Recorder", FakeRecorder)
    monkeypatch.setattr(app_module.messagebox, "askyesno", lambda *a, **k: False)
    return app


def test_recording_creates_a_working_button(recording_app, root, ui, monkeypatch):
    from klickpilot import app as app_module

    monkeypatch.setattr(app_module.simpledialog, "askstring", lambda *a, **k: "Mein Ablauf")
    recording_app.new_button()
    assert recording_app.recorder is not None, "Aufnahme wurde nicht gestartet"

    session = recording_app.recorder.session
    pixel = ui.button_center(1, (300, 200))
    session.mouse_down(1000.0, pixel[0] / 2, pixel[1] / 2)
    session.mouse_up(1000.05, pixel[0] / 2, pixel[1] / 2)
    for offset, character in enumerate("Test"):
        session.key_char(1000.5 + offset * 0.05, character)

    recording_app.stop_recording()
    assert recording_app.recorder is None

    slug = "mein-ablauf"
    macro = recording_app.store.load(slug)
    assert [step.kind for step in macro.steps] == ["click", "text"]
    assert macro.steps[1].text == "Test"
    anchor = macro.steps[0].anchor
    assert recording_app.store.asset_path(slug, anchor.template).exists()
    assert recording_app.store.asset_path(slug, anchor.context).exists()
    assert slug in recording_app.tiles


def test_recorded_button_replays_on_a_moved_window(recording_app, root, ui, monkeypatch):
    import time

    from klickpilot import app as app_module

    monkeypatch.setattr(app_module.simpledialog, "askstring", lambda *a, **k: "Wiedergabe")
    recording_app.new_button()
    session = recording_app.recorder.session
    pixel = ui.button_center(2, (300, 200))
    session.mouse_down(1000.0, pixel[0] / 2, pixel[1] / 2)
    session.mouse_up(1000.05, pixel[0] / 2, pixel[1] / 2)
    recording_app.stop_recording()

    # Das Fenster liegt jetzt woanders - der Button muss trotzdem treffen.
    recording_app._screen.show(ui.render((1150, 700)))
    recording_app.run_macro("wiedergabe")
    deadline = time.time() + 20
    while recording_app.player_thread is not None and time.time() < deadline:
        recording_app._pump()
        time.sleep(0.05)
    recording_app._pump()

    actions = recording_app._inputs.actions
    expected = ui.button_center(2, (1150, 700))
    assert actions and actions[0][0] == "click"
    assert actions[0][1] * 2 == pytest.approx(expected[0], abs=4)
    assert actions[0][2] * 2 == pytest.approx(expected[1], abs=4)


def test_discarded_recording_leaves_nothing_behind(recording_app, monkeypatch):
    from klickpilot import app as app_module

    monkeypatch.setattr(app_module.simpledialog, "askstring", lambda *a, **k: "Verworfen")
    recording_app.new_button()
    recording_app.stop_recording(cancel=True)
    assert recording_app.store.list_macros() == []


def test_appending_keeps_the_earlier_steps(recording_app, ui, monkeypatch):
    from klickpilot import app as app_module

    monkeypatch.setattr(app_module.simpledialog, "askstring", lambda *a, **k: "Zwei Teile")
    recording_app.new_button()
    session = recording_app.recorder.session
    session.key_char(1000.0, "a")
    recording_app.stop_recording()

    recording_app.append_recording("zwei-teile")
    session = recording_app.recorder.session
    session.key_char(2000.0, "b")
    recording_app.stop_recording()

    macro = recording_app.store.load("zwei-teile")
    assert [step.text for step in macro.steps] == ["a", "b"]


def test_tiles_can_be_reordered(app):
    first = add_macro(app, "Alpha", steps=1)
    second = add_macro(app, "Beta", steps=1)
    app.refresh()
    assert [ref.slug for ref in app.store.list_macros()] == [first, second]
    app.move_macro(second, -1)
    assert [ref.slug for ref in app.store.list_macros()] == [second, first]
    app.move_macro(second, -1)  # schon vorne - bleibt so
    assert [ref.slug for ref in app.store.list_macros()] == [second, first]
    app.move_macro(second, 1)
    assert [ref.slug for ref in app.store.list_macros()] == [first, second]
