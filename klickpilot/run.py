"""Einstiegspunkt fuer PyInstaller-Builds (macOS).

Getrennt von `klickpilot/__main__.py` gehalten, da PyInstaller das
Zielskript als eigenstaendiges Top-Level-Modul einfriert - ein relativer
Import (wie in `__main__.py`, dort korrekt fuer `python -m klickpilot`)
wuerde dabei fehlschlagen.
"""
from klickpilot.app import main

if __name__ == "__main__":
    main()
