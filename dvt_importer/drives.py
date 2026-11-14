"""Erkennt eingesteckte Wechseldatenträger (USB-Sticks, CDs/DVDs) auf Windows, macOS und Linux."""
from __future__ import annotations

import getpass
import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Drive:
    path: str
    label: str

    @property
    def display(self) -> str:
        return f"{self.label}  ({self.path})" if self.label else self.path


def _windows_drives() -> list:
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.SetErrorMode(1)  # keine "Kein Datenträger"-Dialoge bei leeren Laufwerken
    drives = []
    bitmask = kernel32.GetLogicalDrives()
    for i in range(26):
        if not bitmask & (1 << i):
            continue
        root = f"{chr(65 + i)}:\\"
        if kernel32.GetDriveTypeW(root) not in (2, 5):  # 2 = Wechseldatenträger, 5 = CD/DVD
            continue
        name = ctypes.create_unicode_buffer(261)
        ok = kernel32.GetVolumeInformationW(root, name, 261, None, None, None, None, 0)
        if not ok:
            continue  # Laufwerk ohne eingelegtes Medium
        drives.append(Drive(path=root, label=name.value or "Wechseldatenträger"))
    return drives


def _mounted_under(*parents) -> list:
    drives = []
    for parent in parents:
        base = Path(parent)
        try:
            entries = sorted(base.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_symlink() or not entry.is_dir() or entry.name.startswith("."):
                    continue
                if not os.path.ismount(entry):
                    continue
            except OSError:
                continue
            drives.append(Drive(path=str(entry), label=entry.name))
    return drives


def list_removable_drives() -> list:
    """Liste der aktuell eingebundenen Wechseldatenträger (leer, wenn keine gefunden)."""
    try:
        if sys.platform == "win32":
            return _windows_drives()
        if sys.platform == "darwin":
            # /Volumes enthält das Startvolume nur als Symlink - der wird übersprungen.
            return _mounted_under("/Volumes")
        user = getpass.getuser()
        return _mounted_under(f"/media/{user}", f"/run/media/{user}", "/media", "/mnt")
    except Exception:  # noqa: BLE001
        return []


def open_in_file_manager(path) -> None:
    """Öffnet einen Ordner im Explorer / Finder."""
    import subprocess

    path = str(path)
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:  # noqa: BLE001
        pass
