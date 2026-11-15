"""Schreibt Fehlerberichte in eine Textdatei im Benutzerordner, damit Startprobleme
der fertig gebauten Anwendung (die kein Konsolenfenster hat) nachvollziehbar sind."""
from __future__ import annotations

import datetime as dt
import platform
import sys
from pathlib import Path

LOG_NAME = "DVT-Sidexis-Importer-Fehler.txt"


def write_crash_log(text: str) -> Path:
    from . import __version__

    path = Path.home() / LOG_NAME
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"\n===== {dt.datetime.now():%Y-%m-%d %H:%M:%S} | Version {__version__} | "
                     f"{platform.platform()} | Python {sys.version.split()[0]} =====\n{text}\n")
    except OSError:
        pass
    return path
