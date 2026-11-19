"""Smoke-Test der Tkinter-Oberfläche: Analyse -> Patientendaten ändern -> Aufbereiten.
Benötigt ein (ggf. virtuelles, z. B. Xvfb) Display; wird sonst übersprungen.
"""
import os
import sys

import pydicom
import pytest
from pydicom.fileset import FileSet

tk = pytest.importorskip("tkinter")

from tests.test_pipeline import make_export  # noqa: E402

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("linux") and not os.environ.get("DISPLAY"), reason="Kein Display verfügbar")


def _drain(app):
    while not app._queue.empty():
        app._handle(*app._queue.get_nowait())


def test_date_helpers():
    from dvt_importer.gui import format_date, parse_date

    assert parse_date("24.12.1985") == "19851224"
    assert parse_date("3.4.85") == "19850403"
    assert parse_date("24121985") == "19851224"
    assert parse_date("19851224") == "19851224"
    assert parse_date("") == ""
    assert format_date("19851224") == "24.12.1985"


def test_gui_full_flow(tmp_path, monkeypatch):
    try:
        from dvt_importer.gui import DvtImporterApp
        app = DvtImporterApp()
    except tk.TclError:
        pytest.skip("Tk kann kein Fenster öffnen")

    from tkinter import messagebox
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(messagebox, "showwarning", lambda *a, **k: None)

    make_export(tmp_path / "usb", [1, 2, 3, 5, 6, 7, 8])   # Schicht 4 fehlt
    try:
        app.source_dir = tmp_path / "usb"
        app._scan_worker()
        _drain(app)
        assert len(app.row_to_series) == 1 and len(app.selected_keys) == 1
        app.update()
        assert app.current_series is not None
        assert app.form_vars["last_name"].get() == "Mustermann"
        assert app.form_vars["birth_date"].get() == "15.03.1970"

        app.form_vars["last_name"].set("Müller")
        app.form_vars["birth_date"].set("24.12.1985")
        app.form_vars["sex"].set("weiblich")
        p = app.current_series.patient
        assert (p.last_name, p.birth_date, p.sex) == ("Müller", "19851224", "F")

        out = tmp_path / "out"
        app._convert_worker(app._selected_series(), out, False)
        _drain(app)
        assert app.last_output == out

        instances = [pydicom.dcmread(i.path) for i in FileSet(str(out / "DICOMDIR"))]
        assert len(instances) == 8
        assert {str(d.PatientName) for d in instances} == {"Müller^Erika"}
    finally:
        app.destroy()


def test_preview_rendering():
    import numpy as np

    from dvt_importer.preview import to_pgm

    data = np.arange(64 * 32, dtype=np.int64).reshape(64, 32)
    pgm = to_pgm(data, 0, 2047, 128)
    header, pixels = pgm.split(b"\n", 1)
    assert header == b"P5 64 128 255" and len(pixels) == 64 * 128
    assert pixels[0] == 0 and pixels[-1] == 255


def test_wizard_full_flow(tmp_path, monkeypatch):
    try:
        from dvt_importer.gui import DvtImporterApp
        app = DvtImporterApp()
    except tk.TclError:
        pytest.skip("Tk kann kein Fenster öffnen")
    from dvt_importer import wizard as wiz_mod

    make_export(tmp_path / "usb", [1, 2, 3, 5, 6, 7, 8])   # Schicht 4 fehlt
    monkeypatch.setattr(wiz_mod, "list_removable_drives", lambda: [])
    wiz = wiz_mod.WizardWindow(app, tmp_path / "ziel")

    def drain():
        while not wiz._queue.empty():
            wiz._handle(*wiz._queue.get_nowait())
        app.update()

    try:
        assert str(wiz.next_btn.cget("state")) == "disabled"     # ohne Auswahl kein „Weiter“
        wiz.custom_folder = tmp_path / "usb"
        wiz.source_var.set(str(tmp_path / "usb"))
        wiz._shown_drives = None
        wiz._refresh_drives()
        assert str(wiz.next_btn.cget("state")) == "normal"

        wiz._scan_worker(wiz.source)
        drain()
        assert len(wiz.volumes) == 1 and wiz.preview is not None
        assert wiz.preview._slots[3] is None                     # Lücke in der Vorschau
        wiz.preview.show(3)
        assert "fehlt" in wiz.preview.info_var.get()
        wiz.preview.show(0)
        assert wiz.preview._photo is not None

        wiz._show_patient()
        wiz.patient_vars["last_name"].set("")
        wiz._patient_next()
        assert wiz.step == 2                                     # bleibt auf der Seite
        wiz.patient_vars["last_name"].set("Müller")
        wiz.patient_vars["birth_date"].set("unsinn")
        wiz._patient_next()
        assert wiz.step == 2
        wiz.patient_vars["birth_date"].set("24.12.1985")
        wiz._patient_next()
        assert wiz.step == 3

        wiz._show_summary()
        out = tmp_path / "ziel" / "test"
        wiz._convert_worker(wiz._selected(), out)
        drain()
        assert wiz.result is not None and wiz.result.verified and wiz.result.black_missing == 1
        assert wiz.path_var.get() == str(out)
        names = {str(pydicom.dcmread(i.path).PatientName) for i in FileSet(str(out / "DICOMDIR"))}
        assert names == {"Müller^Erika"}
    finally:
        wiz.destroy()
        app.destroy()


def test_wizard_card_selection_drives_preview(tmp_path, monkeypatch):
    try:
        from dvt_importer.gui import DvtImporterApp
        app = DvtImporterApp()
    except tk.TclError:
        pytest.skip("Tk kann kein Fenster öffnen")
    from dvt_importer import wizard as wiz_mod
    from dvt_importer.scanner import scan_source

    monkeypatch.setattr(wiz_mod, "list_removable_drives", lambda: [])
    for name, count in (("A", 9), ("B", 7), ("C", 6)):
        make_export(tmp_path / "usb" / name, range(1, count + 1), patient_id=name)
    wiz = wiz_mod.WizardWindow(app, tmp_path / "ziel")
    try:
        wiz.source, wiz.source_label = tmp_path / "usb", "USB"
        wiz._on_scanned(scan_source(tmp_path / "usb"))
        app.update()
        assert len(wiz.volumes) == 3
        assert wiz.preview._series is wiz.volumes[0]           # erste Aufnahme vorausgewählt

        # Klick irgendwo auf die zweite Karte -> rechts erscheint diese Aufnahme
        wiz.cards.cards[1]["widgets"][-1].event_generate("<Button-1>", x=5, y=5)
        app.update()
        assert wiz.cards.index == 1 and wiz.preview._series is wiz.volumes[1]

        # Häkchen der dritten Karte abwählen: wird nicht übernommen, Auswahl springt mit
        wiz.cards.cards[2]["box"].event_generate("<Button-1>", x=10, y=10)
        app.update()
        assert wiz._selected() == wiz.volumes[:2]
        assert wiz.preview._series is wiz.volumes[2]

        # Pfeiltasten wechseln ebenfalls die Vorschau
        wiz.cards.move(-1)
        assert wiz.preview._series is wiz.volumes[1]

        # Alle abgewählt -> kein "Weiter"
        for i in (0, 1):
            wiz.cards._toggle(i)
        assert str(wiz.next_btn.cget("state")) == "disabled"
    finally:
        wiz.destroy()
        app.destroy()
