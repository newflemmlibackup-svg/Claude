"""Anwendungseinstellungen, persistiert unter ~/.klickpilot/config.json."""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".klickpilot"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    # Ablageort der aufgenommenen Ablaeufe (ein Unterordner je Button).
    "data_root": str(Path.home() / "Klickpilot"),
    # Ab welcher Aehnlichkeit (0..1) ein Bedienelement als wiedererkannt gilt.
    "match_threshold": 0.78,
    # Gewicht des grossen Umgebungsausschnitts bei der Gesamtbewertung.
    "context_weight": 0.35,
    # Aufgenommene Pausen werden auf diesen Wert gedeckelt (Sekunden).
    "max_delay": 3.0,
    # Wiedergabegeschwindigkeit (2.0 = doppelt so schnell wie aufgenommen).
    "speed": 1.0,
    # Countdown vor Aufnahme bzw. Wiedergabe (Sekunden).
    "countdown": 3,
    # Wie lange auf das Erscheinen eines Bedienelements gewartet wird.
    "anchor_timeout": 8.0,
    # Groesse der gespeicherten Ausschnitte in Punkten (Breite, Hoehe).
    "template_size": [110, 70],
    "context_size": [420, 280],
    # Bildrate des Mitschnitt-Puffers waehrend der Aufnahme.
    "record_fps": 6.0,
    "hide_window_on_record": True,
    "hide_window_on_run": True,
    "settle_after_click": 0.25,
    "stop_hotkey": "<f9>",
    "panic_hotkey": "<f10>",
    "columns": 3,
}


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_CONFIG)
    merged = dict(DEFAULT_CONFIG)
    if isinstance(data, dict):
        merged.update(data)
    return merged


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)
    tmp.replace(CONFIG_PATH)


def data_root(config: dict | None = None) -> Path:
    cfg = config or load_config()
    root = Path(cfg.get("data_root") or DEFAULT_CONFIG["data_root"]).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root
