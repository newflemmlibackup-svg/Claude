"""Einstiegspunkt für die fertig gebaute Anwendung (PyInstaller, Windows/macOS)."""
import sys

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        from dvt_importer.selftest import run

        sys.exit(run())
    from dvt_importer.gui import main

    main()
