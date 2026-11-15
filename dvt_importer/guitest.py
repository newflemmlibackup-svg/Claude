"""Oberflächentest (`--guitest`): startet die echte Anwendung samt Ereignisschleife,
öffnet den geführten Modus und die Vorschau und beendet sich wieder.
Rückgabewert 0 = Fenster ließen sich fehlerfrei öffnen."""
from __future__ import annotations

import tempfile
import traceback
from pathlib import Path


def run() -> int:
    errors: list = []
    try:
        import numpy as np
        import pydicom
        from pydicom.dataset import Dataset

        from .gui import DvtImporterApp
        from .preview import open_preview_window
        from .scanner import scan_source
        from .wizard import WizardWindow

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "quelle"
            src.mkdir()
            for i in range(1, 9):
                ds = Dataset()
                ds.PatientName, ds.PatientID, ds.Modality = "Test^Fenster", "T1", "CT"
                ds.Rows = ds.Columns = 48
                ds.BitsAllocated = ds.BitsStored = 16
                ds.HighBit, ds.PixelRepresentation, ds.SamplesPerPixel = 15, 0, 1
                ds.PhotometricInterpretation = "MONOCHROME2"
                ds.InstanceNumber = i
                ds.ImagePositionPatient = [0, 0, i * 0.3]
                ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
                ds.PixelSpacing = [0.3, 0.3]
                ds.PixelData = (np.arange(48 * 48, dtype=np.uint16) * i).tobytes()
                pydicom.dcmwrite(str(src / f"IMG{i:03d}"), ds, implicit_vr=True, little_endian=True,
                                 enforce_file_format=False)

            app = DvtImporterApp()
            app.report_callback_exception = lambda *exc: errors.append("".join(traceback.format_exception(*exc)))
            state: dict = {}

            def step1():   # Hauptfenster füllen + Vorschaufenster
                app._populate_tree(scan_source(src))
                app._on_tree_select()
                assert app.current_series is not None, "keine Aufnahme ausgewählt"
                state["preview"] = open_preview_window(app, app.current_series)

            def step2():   # geführter Modus bis zur Vorschau-Seite
                state["preview"].destroy()
                app._open_wizard()
                wiz = next(c for c in app.winfo_children() if isinstance(c, WizardWindow))
                state["wiz"] = wiz
                wiz.source, wiz.source_label = src, "Test"
                wiz._on_scanned(scan_source(src))
                assert wiz.preview is not None and wiz.preview._photo is not None, "Vorschau leer"

            def inside(window, widget) -> bool:
                """Liegt das Bedienelement vollständig im sichtbaren Fensterbereich?"""
                window.update_idletasks()
                return (widget.winfo_rooty() + widget.winfo_height() <= window.winfo_rooty() + window.winfo_height()
                        and widget.winfo_rootx() + widget.winfo_width() <= window.winfo_rootx() + window.winfo_width()
                        and widget.winfo_height() > 5)

            def step3():
                wiz = state["wiz"]
                for name, widget in (("Weiter", wiz.next_btn), ("Vorschau", wiz.preview.info)):
                    if not inside(wiz, widget):
                        errors.append(f"Geführter Modus: „{name}“ liegt außerhalb des Fensters")
                wiz._show_patient()
                for name, widget in (("Aufbereiten-Knopf", app.convert_btn), ("Protokoll", app.log_text),
                                     ("Felix-Knopf", app.wizard_btn), ("Patientendaten", app.apply_all_btn),
                                     ("Vorschau-Knopf", app.preview_btn)):
                    if not inside(app, widget):
                        errors.append(f"Hauptfenster {app.geometry()}: „{name}“ liegt außerhalb des Fensters")

            def step4():
                state["wiz"]._close()
                state["ok"] = app.winfo_viewable() == 1 and app.winfo_height() > 300
                app.destroy()

            for delay, func in ((700, step1), (1500, step2), (2300, step3), (3000, step4)):
                app.after(delay, func)
            app.after(15000, app.destroy)   # Notbremse
            app.mainloop()
            if not state.get("ok"):
                errors.append("Hauptfenster wurde nicht sichtbar oder Ablauf unvollständig")
    except Exception:  # noqa: BLE001
        errors.append(traceback.format_exc())
    if errors:
        print("\n".join(errors))
        from .crashlog import write_crash_log

        write_crash_log("GUI-Test:\n" + "\n".join(errors))
        return 1
    print("Oberflächentest bestanden.")
    return 0
