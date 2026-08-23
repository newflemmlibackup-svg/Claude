"""Ablage der Buttons als Ordnerstruktur:

<Datenordner>/
  rechnung-drucken/
    macro.json          Schrittfolge
    assets/
      a0001.png         gemerkter Bildausschnitt (Schablone)
      a0001_ctx.png     zugehoeriger Umgebungsausschnitt

Ein Button ist damit vollstaendig eigenstaendig und laesst sich als Ordner
oder ZIP-Datei kopieren, sichern und an einen anderen Mac weitergeben.
"""
from __future__ import annotations

import json
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np

from . import imaging
from .models import Macro

MACRO_FILENAME = "macro.json"
ASSET_DIRNAME = "assets"
ORDER_FILENAME = ".reihenfolge.json"


def slugify(name: str) -> str:
    text = name.strip().lower()
    for source, target in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(source, target)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "button"


@dataclass
class MacroRef:
    slug: str
    name: str
    path: Path
    hotkey: str = ""
    steps: int = 0


class Store:
    """Zugriff auf den Datenordner mit allen Buttons."""

    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    # -- Pfade ---------------------------------------------------------
    def macro_dir(self, slug: str) -> Path:
        return self.root / slug

    def asset_dir(self, slug: str) -> Path:
        return self.macro_dir(slug) / ASSET_DIRNAME

    def asset_path(self, slug: str, name: str) -> Path:
        return self.asset_dir(slug) / name

    # -- Auflisten -----------------------------------------------------
    def list_macros(self) -> List[MacroRef]:
        refs: List[MacroRef] = []
        for entry in sorted(self.root.iterdir() if self.root.exists() else []):
            path = entry / MACRO_FILENAME
            if not entry.is_dir() or not path.exists():
                continue
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            refs.append(
                MacroRef(
                    slug=entry.name,
                    name=str(data.get("name", entry.name)),
                    path=entry,
                    hotkey=str(data.get("hotkey", "")),
                    steps=len(data.get("steps", []) or []),
                )
            )
        order = self._load_order()
        refs.sort(key=lambda ref: (order.index(ref.slug) if ref.slug in order else len(order), ref.name.lower()))
        return refs

    def _load_order(self) -> List[str]:
        path = self.root / ORDER_FILENAME
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return [str(item) for item in data] if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def save_order(self, slugs: List[str]) -> None:
        with open(self.root / ORDER_FILENAME, "w", encoding="utf-8") as handle:
            json.dump(list(slugs), handle, indent=2)

    # -- Lesen/Schreiben -----------------------------------------------
    def load(self, slug: str) -> Macro:
        with open(self.macro_dir(slug) / MACRO_FILENAME, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return Macro.from_dict(data, slug=slug)

    def create(self, name: str) -> str:
        """Legt einen leeren Button an und liefert dessen Kennung (slug)."""
        slug = self._free_slug(slugify(name))
        self.asset_dir(slug).mkdir(parents=True, exist_ok=True)
        self.save(Macro(name=name, slug=slug))
        return slug

    def _free_slug(self, base: str) -> str:
        candidate = base
        counter = 2
        while self.macro_dir(candidate).exists():
            candidate = f"{base}-{counter}"
            counter += 1
        return candidate

    def save(self, macro: Macro) -> None:
        if not macro.slug:
            macro.slug = self._free_slug(slugify(macro.name))
        directory = self.macro_dir(macro.slug)
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / (MACRO_FILENAME + ".tmp")
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(macro.to_dict(), handle, indent=2, ensure_ascii=False)
        temporary.replace(directory / MACRO_FILENAME)

    def delete(self, slug: str) -> None:
        shutil.rmtree(self.macro_dir(slug), ignore_errors=True)

    def rename(self, slug: str, new_name: str) -> None:
        macro = self.load(slug)
        macro.name = new_name
        self.save(macro)

    def duplicate(self, slug: str, new_name: Optional[str] = None) -> str:
        macro = self.load(slug)
        target = self._free_slug(slugify(new_name or (macro.name + " Kopie")))
        shutil.copytree(self.macro_dir(slug), self.macro_dir(target))
        copy = self.load(target)
        copy.slug = target
        copy.name = new_name or (macro.name + " Kopie")
        copy.hotkey = ""
        self.save(copy)
        return target

    # -- Bildausschnitte ------------------------------------------------
    def store_asset(self, slug: str, image: np.ndarray, name: str) -> str:
        imaging.save_image(self.asset_path(slug, name), image)
        return name

    def load_asset(self, slug: str, name: str) -> Optional[np.ndarray]:
        path = self.asset_path(slug, name)
        if not path.exists():
            return None
        return imaging.load_image(path)

    def next_asset_index(self, slug: str) -> int:
        directory = self.asset_dir(slug)
        if not directory.exists():
            return 1
        highest = 0
        for entry in directory.glob("a*.png"):
            match = re.match(r"a(\d+)", entry.stem)
            if match:
                highest = max(highest, int(match.group(1)))
        return highest + 1

    def prune_assets(self, macro: Macro) -> int:
        """Loescht Bildausschnitte, die von keinem Schritt mehr benutzt werden."""
        used = set(macro.asset_names())
        removed = 0
        directory = self.asset_dir(macro.slug)
        if not directory.exists():
            return 0
        for entry in directory.glob("*.png"):
            if entry.name not in used:
                entry.unlink(missing_ok=True)
                removed += 1
        return removed

    # -- Weitergabe -----------------------------------------------------
    def export_zip(self, slug: str, target: Path | str) -> Path:
        target = Path(target)
        directory = self.macro_dir(slug)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(directory.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(directory).as_posix())
        return target

    def import_zip(self, source: Path | str) -> str:
        source = Path(source)
        with zipfile.ZipFile(source) as archive:
            names = archive.namelist()
            if MACRO_FILENAME not in names:
                raise ValueError("Die Datei enthaelt keinen Klickpilot-Button (macro.json fehlt).")
            for name in names:
                if name.startswith("/") or ".." in Path(name).parts:
                    raise ValueError(f"Unerlaubter Pfad im Archiv: {name}")
            slug = self._free_slug(slugify(source.stem))
            directory = self.macro_dir(slug)
            directory.mkdir(parents=True, exist_ok=True)
            archive.extractall(directory)
        macro = self.load(slug)
        macro.slug = slug
        macro.hotkey = ""
        self.save(macro)
        return slug
