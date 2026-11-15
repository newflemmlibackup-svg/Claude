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


_NETWORK_FS = {"smbfs", "afpfs", "nfs", "webdav", "autofs", "ftp", "cifs", "fuse.sshfs", "devfs"}


def _macos_drives() -> list:
    """Eingebundene Datenträger unter /Volumes aus der Ausgabe von `mount`.

    Bewusst ohne Dateizugriffe auf die Volumes selbst: Ein nicht erreichbares
    Netzlaufwerk (Praxis-Server) würde solche Zugriffe minutenlang blockieren.
    """
    import re
    import subprocess

    out = subprocess.run(["/sbin/mount"], capture_output=True, text=True, timeout=5).stdout
    drives = []
    for line in out.splitlines():
        m = re.match(r"^(.*?) on (/Volumes/.+?) \(([^,)]+)", line)
        if not m:
            continue
        path, fs_type = m.group(2), m.group(3).strip().lower()
        if fs_type in _NETWORK_FS or "/" in path[len("/Volumes/"):]:
            continue
        drives.append(Drive(path=path, label=path[len("/Volumes/"):]))
    return sorted(drives, key=lambda d: d.path)


def list_removable_drives() -> list:
    """Liste der aktuell eingebundenen Wechseldatenträger (leer, wenn keine gefunden)."""
    try:
        if sys.platform == "win32":
            return _windows_drives()
        if sys.platform == "darwin":
            return _macos_drives()
        user = getpass.getuser()
        return _mounted_under(f"/media/{user}", f"/run/media/{user}", "/media", "/mnt")
    except Exception:  # noqa: BLE001
        return []


class _DriveWatcher:
    """Fragt die Datenträger in einem Hintergrund-Thread ab.

    Die Oberfläche liest nur das zuletzt ermittelte Ergebnis und kann deshalb
    nie hängen bleiben - egal wie lange das Betriebssystem für die Antwort braucht.
    """

    def __init__(self, interval: float = 2.0):
        import threading

        self._interval = interval
        self._latest: list = []
        self._started = False
        self._lock = threading.Lock()

    def latest(self) -> list:
        import threading

        with self._lock:
            if not self._started:
                self._started = True
                threading.Thread(target=self._run, daemon=True, name="drive-watcher").start()
            return list(self._latest)

    def _run(self):
        import time

        while True:
            drives = list_removable_drives()
            with self._lock:
                self._latest = drives
            time.sleep(self._interval)


_watcher = _DriveWatcher()


def cached_removable_drives() -> list:
    """Zuletzt bekannte Datenträger - kehrt sofort zurück (anfangs ggf. leere Liste)."""
    return _watcher.latest()


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
