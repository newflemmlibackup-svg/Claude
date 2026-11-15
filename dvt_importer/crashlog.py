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


# ----------------------------------------------------------------- Startprotokoll
_trace_file = None


def log_dir() -> Path:
    if sys.platform == "darwin":
        path = Path.home() / "Library" / "Logs" / "DVT-Sidexis-Importer"
    else:
        import tempfile

        path = Path(tempfile.gettempdir()) / "DVT-Sidexis-Importer"
    path.mkdir(parents=True, exist_ok=True)
    return path


def start_trace(message: str) -> None:
    """Hält jeden Startschritt mit Uhrzeit fest. Bleibt der Start hängen, schreibt
    Python nach 20 Sekunden automatisch dazu, an welcher Stelle."""
    global _trace_file
    try:
        if _trace_file is None:
            import faulthandler

            from . import __version__

            _trace_file = open(log_dir() / "start.log", "w", encoding="utf-8", buffering=1)
            _trace_file.write(f"Version {__version__} | {platform.platform()} | {platform.machine()} | "
                              f"Python {sys.version.split()[0]}\n")
            faulthandler.enable(file=_trace_file)
            faulthandler.dump_traceback_later(20, file=_trace_file)
        _trace_file.write(f"{dt.datetime.now():%H:%M:%S.%f} {message}\n")
    except Exception:  # noqa: BLE001 - das Protokoll darf den Start nie verhindern
        pass


def startup_done() -> None:
    try:
        import faulthandler

        faulthandler.cancel_dump_traceback_later()
    except Exception:  # noqa: BLE001
        pass
