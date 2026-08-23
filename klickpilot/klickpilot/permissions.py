"""Pruefung der macOS-Freigaben.

Klickpilot braucht zwei Berechtigungen:

* **Bedienungshilfen** - um Tastatur/Maus mitzulesen und selbst zu steuern.
* **Bildschirmaufnahme** - um Bildschirmfotos fuer die Wiedererkennung zu
  machen.

Beide werden pro Programm vergeben. Wird Klickpilot aus dem Terminal
gestartet, fragt macOS die Rechte fuer das Terminal ab.
"""
from __future__ import annotations

import platform
import subprocess
from typing import List

ACCESSIBILITY_PANE = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
)
SCREEN_PANE = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
)


def is_macos() -> bool:
    return platform.system() == "Darwin"


def has_accessibility() -> bool:
    """Darf Klickpilot Eingaben mitlesen *und* selbst ausloesen?

    Beides haengt an derselben Freigabe, wird von macOS aber getrennt
    abgefragt: Mitlesen (Aufnahme) und Senden (Wiedergabe).
    """
    try:
        import Quartz

        checks = [
            getattr(Quartz, name, None)
            for name in ("CGPreflightListenEventAccess", "CGPreflightPostEventAccess")
        ]
        answers = [bool(check()) for check in checks if check is not None]
        if answers:
            return all(answers)
        from ApplicationServices import AXIsProcessTrusted

        return bool(AXIsProcessTrusted())
    except Exception:
        return False


def request_accessibility() -> None:
    asked = False
    try:
        import Quartz

        for name in ("CGRequestListenEventAccess", "CGRequestPostEventAccess"):
            request = getattr(Quartz, name, None)
            if request is not None:
                request()
                asked = True
    except Exception:
        asked = False
    if not asked:
        open_pane(ACCESSIBILITY_PANE)


def has_screen_recording() -> bool:
    try:
        import Quartz

        if hasattr(Quartz, "CGPreflightScreenCaptureAccess"):
            return bool(Quartz.CGPreflightScreenCaptureAccess())
    except Exception:
        return False
    # Aeltere Systeme kennen die Abfrage nicht - Probeaufnahme machen.
    try:
        import Quartz

        return Quartz.CGDisplayCreateImage(Quartz.CGMainDisplayID()) is not None
    except Exception:
        return False


def request_screen_recording() -> None:
    try:
        import Quartz

        if hasattr(Quartz, "CGRequestScreenCaptureAccess"):
            Quartz.CGRequestScreenCaptureAccess()
            return
    except Exception:
        pass
    open_pane(SCREEN_PANE)


def open_pane(url: str) -> None:
    try:
        subprocess.run(["open", url], check=False, capture_output=True)
    except Exception:
        pass


def missing() -> List[str]:
    """Namen der noch fehlenden Freigaben."""
    if not is_macos():
        return []
    gaps = []
    if not has_accessibility():
        gaps.append("Bedienungshilfen")
    if not has_screen_recording():
        gaps.append("Bildschirmaufnahme")
    return gaps


HINT = (
    "Klickpilot benoetigt zwei Freigaben in den Systemeinstellungen unter\n"
    "'Datenschutz & Sicherheit':\n\n"
    "  1. Bedienungshilfen  - Maus und Tastatur steuern\n"
    "  2. Bildschirmaufnahme - Bedienelemente wiedererkennen\n\n"
    "Nach dem Erteilen muss Klickpilot einmal neu gestartet werden."
)
