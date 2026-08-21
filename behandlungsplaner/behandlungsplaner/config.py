"""Anwendungseinstellungen (Praxis-Datenordner, Praxisname, Preislisten-
Vorgaben), persistiert unter ~/.behandlungsplaner/config.json."""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".behandlungsplaner"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "data_root": str(Path.home() / "Behandlungsplaene"),
    "clinic_name": "",
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
    merged.update(data)
    return merged


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)
