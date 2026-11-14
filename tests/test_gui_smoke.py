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
