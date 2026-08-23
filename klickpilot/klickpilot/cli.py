"""Kommandozeile - nuetzlich fuer Automatisierung ohne Fenster,
z. B. um einen Ablauf aus einem anderen Skript heraus zu starten."""
from __future__ import annotations

import argparse
import sys
import time
from typing import Optional

from . import APP_NAME, __version__, permissions
from .anchors import AnchorFactory
from .config import data_root, load_config
from .storage import Store


def _find_slug(store: Store, needle: str) -> Optional[str]:
    needle_lower = needle.strip().lower()
    for ref in store.list_macros():
        if needle_lower in (ref.slug.lower(), ref.name.lower()):
            return ref.slug
    for ref in store.list_macros():
        if needle_lower in ref.name.lower():
            return ref.slug
    return None


def command_list(store: Store) -> int:
    refs = store.list_macros()
    if not refs:
        print("Noch keine Buttons vorhanden.")
        return 0
    width = max(len(ref.name) for ref in refs)
    for ref in refs:
        hotkey = f"  [{ref.hotkey}]" if ref.hotkey else ""
        print(f"{ref.name.ljust(width)}   {ref.steps:>3} Schritte   ({ref.slug}){hotkey}")
    return 0


def _require_macos() -> bool:
    if permissions.is_macos():
        return True
    print("Aufnahme und Wiedergabe brauchen macOS - hier laeuft ein anderes System.",
          file=sys.stderr)
    return False


def command_run(store: Store, config: dict, name: str, countdown: int) -> int:
    if not _require_macos():
        return 3
    slug = _find_slug(store, name)
    if slug is None:
        print(f"Kein Button mit dem Namen '{name}' gefunden.", file=sys.stderr)
        return 2
    macro = store.load(slug)
    if not macro.steps:
        print("Dieser Button enthaelt keine Schritte.", file=sys.stderr)
        return 2
    from .inputs import get_input_backend
    from .player import Player
    from .screen import get_screen

    for remaining in range(countdown, 0, -1):
        print(f"Start in {remaining} ...", end="\r", flush=True)
        time.sleep(1)
    player = Player(get_screen(), get_input_backend(), store, config,
                    on_event=lambda event: print(f"  {event.message}"))
    result = player.run(macro)
    print("Fertig." if result.ok else f"Abgebrochen: {result.message}")
    return 0 if result.ok else 1


def command_record(store: Store, config: dict, name: str, append: bool, seconds: float) -> int:
    if not _require_macos():
        return 3
    slug = _find_slug(store, name)
    if slug is None:
        slug = store.create(name)
        append = False
    macro = store.load(slug)
    if not append:
        macro.steps = []
    from .inputs import get_input_backend
    from .recorder import Recorder, RecordingSession
    from .screen import ScreenBuffer, get_screen

    backend = get_input_backend()
    buffer = ScreenBuffer(get_screen(), fps=float(config.get("record_fps", 6.0)),
                          locator=backend.mouse_position)
    factory = AnchorFactory(store, slug, config)
    session = RecordingSession(
        factory.make, buffer.frame_for, config,
        on_step=lambda step: print(f"  {len(session.steps):>3}. {step.describe()}"),
    )
    recorder = Recorder(session, buffer=buffer)
    print(f"Aufnahme fuer '{macro.name}' startet in 3 Sekunden ...")
    time.sleep(3)
    recorder.start()
    print(f"Aufnahme laeuft - Ende mit Strg+C{'' if seconds <= 0 else f' oder nach {seconds:.0f} s'}.")
    try:
        deadline = time.time() + seconds if seconds > 0 else None
        while deadline is None or time.time() < deadline:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    steps = recorder.stop()
    macro.steps = list(macro.steps) + list(steps) if append else list(steps)
    store.save(macro)
    store.prune_assets(macro)
    print(f"\n{len(macro.steps)} Schritte gespeichert unter {store.macro_dir(slug)}")
    return 0


def command_check() -> int:
    if not permissions.is_macos():
        print("Hinweis: Aufnahme und Wiedergabe laufen nur unter macOS.")
        return 1
    gaps = permissions.missing()
    if gaps:
        print("Es fehlen Freigaben: " + ", ".join(gaps))
        print()
        print(permissions.HINT)
        return 1
    print("Alle Freigaben sind erteilt.")
    return 0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="klickpilot",
        description=f"{APP_NAME} - Klickablaeufe aufnehmen und mit Bilderkennung abspielen.",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument("--list", action="store_true", help="Vorhandene Buttons auflisten")
    parser.add_argument("--run", metavar="NAME", help="Einen Button ausfuehren")
    parser.add_argument("--record", metavar="NAME", help="Einen Button aufnehmen (Ende mit Strg+C)")
    parser.add_argument("--append", action="store_true", help="Bei --record: Schritte anhaengen")
    parser.add_argument("--seconds", type=float, default=0.0, help="Bei --record: nach n Sekunden beenden")
    parser.add_argument("--countdown", type=int, default=3, help="Bei --run: Countdown in Sekunden")
    parser.add_argument("--check", action="store_true", help="macOS-Freigaben pruefen")
    arguments = parser.parse_args(argv)

    config = load_config()
    store = Store(data_root(config))

    if arguments.check:
        return command_check()
    if arguments.list:
        return command_list(store)
    if arguments.run:
        return command_run(store, config, arguments.run, max(0, arguments.countdown))
    if arguments.record:
        return command_record(store, config, arguments.record, arguments.append, arguments.seconds)

    from .app import main as gui_main

    gui_main()
    return 0
