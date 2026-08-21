"""Einstiegspunkt fuer PyInstaller-Builds (Windows/macOS).

Wird separat von `dvt_importer/__main__.py` gehalten, da PyInstaller das
Zielskript als eigenstaendiges Top-Level-Modul einfriert - ein relativer
Import (wie in `__main__.py`, dort korrekt fuer `python -m dvt_importer`)
wuerde dabei fehlschlagen.
"""
from dvt_importer.gui import main

if __name__ == "__main__":
    main()
