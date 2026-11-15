"""Einstiegspunkt für die fertig gebaute Anwendung (PyInstaller, Windows/macOS)."""
import sys


def _start() -> int:
    if "--selftest" in sys.argv:
        from dvt_importer.selftest import run

        return run()
    if "--guitest" in sys.argv:
        from dvt_importer.guitest import run

        return run()
    try:
        from dvt_importer.gui import main

        main()
        return 0
    except Exception:  # noqa: BLE001 - Startfehler sichtbar machen statt stumm zu beenden
        import traceback

        from dvt_importer.crashlog import write_crash_log

        path = write_crash_log(traceback.format_exc())
        try:
            import tkinter
            from tkinter import messagebox

            root = tkinter.Tk()
            root.withdraw()
            messagebox.showerror("DVT-Sidexis-Importer",
                                 f"Das Programm konnte nicht gestartet werden.\n\nDetails stehen in:\n{path}")
        except Exception:  # noqa: BLE001
            pass
        return 1


if __name__ == "__main__":
    sys.exit(_start())
