"""Einstiegspunkt fuer PyInstaller-Builds (Windows/macOS).

Getrennt von `behandlungsplaner/__main__.py` gehalten, da PyInstaller das
Zielskript als eigenstaendiges Top-Level-Modul einfriert - ein relativer
Import (wie in `__main__.py`, dort korrekt fuer `python -m behandlungsplaner`)
wuerde dabei fehlschlagen.
"""
from behandlungsplaner.app import main

if __name__ == "__main__":
    main()
