"""Smoke-Test fuer die Tkinter-GUI: prueft, dass sich das Fenster aufbauen laesst
und der komplette Scan->Auswahl->Konvertieren-Ablauf ohne Exceptions durchlaeuft.
Erfordert ein (ggf. virtuelles, z.B. Xvfb) Display; wird sonst uebersprungen.
"""
import os

import pytest

tk = pytest.importorskip("tkinter")

from tests.test_pipeline import make_broken_no_uid_export  # noqa: E402


def _tk_available() -> bool:
    try:
        root = tk.Tk()
        root.destroy()
        return True
    except tk.TclError:
        return False


pytestmark = pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="Kein Display verfuegbar")


def test_gui_full_flow(tmp_path):
    if not _tk_available():
        pytest.skip("Tk kann kein Fenster oeffnen (kein funktionierendes Display)")

    from dvt_importer.gui import DvtImporterApp

    source = tmp_path / "usb"
    make_broken_no_uid_export(source, num_slices=5)
    dest = tmp_path / "sidexis_out"

    app = DvtImporterApp()
    try:
        app.source_dir = source
        app._scan_worker()  # synchron statt in eigenem Thread

        # Queue wie beim regulaeren Polling abarbeiten.
        while not app._log_queue.empty():
            kind, payload = app._log_queue.get_nowait()
            if kind == "SCAN_RESULT":
                app._populate_tree(payload)

        assert len(app.row_id_to_series) == 1
        app._select_all()
        assert len(app.selected_keys) == 1

        app.dest_dir = dest
        selected_series = [s for s in app.scan_result.series if s.key in app.selected_keys]
        app._convert_worker(selected_series)

        result = None
        while not app._log_queue.empty():
            kind, payload = app._log_queue.get_nowait()
            if kind == "CONVERT_RESULT":
                result = payload

        assert result is not None
        assert result.images_converted == 5
        assert (dest / "DICOMDIR").exists()
    finally:
        app.destroy()
