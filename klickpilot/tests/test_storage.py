"""Ablage: anlegen, sichern, laden, weitergeben."""
from __future__ import annotations

import json

import numpy as np
import pytest

from klickpilot.models import CLICK, Anchor, Step
from klickpilot.storage import Store, slugify


def test_slugify_handles_umlauts_and_spaces():
    assert slugify("Roentgen Befund äöü") == "roentgen-befund-aeoeue"
    assert slugify("!!!") == "button"


def test_create_makes_a_unique_folder(store):
    first = store.create("Termin")
    second = store.create("Termin")
    assert first == "termin" and second == "termin-2"
    assert store.macro_dir(first).is_dir()


def test_save_and_load_round_trip(store):
    slug = store.create("Ablauf")
    macro = store.load(slug)
    macro.steps = [
        Step(kind=CLICK, anchor=Anchor(template="a0001.png", size=(20, 10), hotspot=(10, 5)),
             clicks=2, delay_before=0.75, note="Knopf Speichern"),
    ]
    macro.hotkey = "cmd+shift+1"
    store.save(macro)

    again = store.load(slug)
    assert again.name == "Ablauf" and again.hotkey == "cmd+shift+1"
    assert again.steps[0].clicks == 2
    assert again.steps[0].delay_before == pytest.approx(0.75)
    assert again.steps[0].anchor.hotspot == (10, 5)
    assert again.steps[0].note == "Knopf Speichern"


def test_list_macros_reports_step_count(store):
    slug = store.create("Zwei Schritte")
    macro = store.load(slug)
    macro.steps = [Step(kind=CLICK), Step(kind=CLICK)]
    store.save(macro)
    refs = store.list_macros()
    assert len(refs) == 1 and refs[0].steps == 2 and refs[0].name == "Zwei Schritte"


def test_assets_are_numbered_consecutively(store):
    slug = store.create("Bilder")
    image = (np.random.default_rng(1).random((8, 12, 3)) * 255).astype(np.uint8)
    assert store.next_asset_index(slug) == 1
    store.store_asset(slug, image, "a0001.png")
    store.store_asset(slug, image, "a0007.png")
    assert store.next_asset_index(slug) == 8
    assert store.load_asset(slug, "a0001.png").shape == (8, 12, 3)
    assert store.load_asset(slug, "fehlt.png") is None


def test_prune_removes_unused_assets(store):
    slug = store.create("Aufraeumen")
    image = np.zeros((4, 4, 3), np.uint8)
    store.store_asset(slug, image, "a0001.png")
    store.store_asset(slug, image, "a0002.png")
    macro = store.load(slug)
    macro.steps = [Step(kind=CLICK, anchor=Anchor(template="a0001.png"))]
    store.save(macro)
    assert store.prune_assets(macro) == 1
    assert store.asset_path(slug, "a0001.png").exists()
    assert not store.asset_path(slug, "a0002.png").exists()


def test_export_and_import(store, tmp_path):
    slug = store.create("Zum Verschicken")
    store.store_asset(slug, np.zeros((4, 4, 3), np.uint8), "a0001.png")
    macro = store.load(slug)
    macro.steps = [Step(kind=CLICK, anchor=Anchor(template="a0001.png"))]
    macro.hotkey = "f7"
    store.save(macro)

    archive = store.export_zip(slug, tmp_path / "verschickt.zip")
    other = Store(tmp_path / "anderer-mac")
    imported = other.import_zip(archive)
    loaded = other.load(imported)
    assert loaded.name == "Zum Verschicken"
    assert other.asset_path(imported, "a0001.png").exists()
    assert loaded.hotkey == "", "Kuerzel duerfen sich beim Import nicht ueberschneiden"


def test_import_rejects_foreign_archives(store, tmp_path):
    import zipfile

    bad = tmp_path / "fremd.zip"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("irgendwas.txt", "hallo")
    with pytest.raises(ValueError):
        store.import_zip(bad)


def test_duplicate_copies_steps_and_assets(store):
    slug = store.create("Original")
    store.store_asset(slug, np.zeros((4, 4, 3), np.uint8), "a0001.png")
    macro = store.load(slug)
    macro.steps = [Step(kind=CLICK, anchor=Anchor(template="a0001.png"))]
    macro.hotkey = "f8"
    store.save(macro)
    copy_slug = store.duplicate(slug)
    copy = store.load(copy_slug)
    assert copy.name == "Original Kopie" and len(copy.steps) == 1
    assert copy.hotkey == ""
    assert store.asset_path(copy_slug, "a0001.png").exists()


def test_broken_macro_file_is_skipped(store):
    slug = store.create("Kaputt")
    (store.macro_dir(slug) / "macro.json").write_text("{kein json", encoding="utf-8")
    assert store.list_macros() == []


def test_saved_file_is_readable_json(store):
    slug = store.create("Lesbar")
    with open(store.macro_dir(slug) / "macro.json", encoding="utf-8") as handle:
        data = json.load(handle)
    assert data["name"] == "Lesbar" and data["steps"] == []


def test_custom_order_is_kept(store):
    store.create("Bravo")
    store.create("Alpha")
    store.save_order(["bravo", "alpha"])
    assert [ref.slug for ref in store.list_macros()] == ["bravo", "alpha"]
