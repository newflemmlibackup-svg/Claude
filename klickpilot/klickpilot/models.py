"""Datenmodell: ein Button (Makro) besteht aus einer Folge von Schritten,
jeder Schritt haengt an einem "Anker" - dem gemerkten Aussehen der Stelle,
auf die geklickt wurde."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

CLICK = "click"
DRAG = "drag"
SCROLL = "scroll"
TEXT = "text"
KEY = "key"
WAIT = "wait"
WAIT_IMAGE = "wait_image"

ON_ERROR_ABORT = "abort"
ON_ERROR_SKIP = "skip"
ON_ERROR_RETRY = "retry"

BUTTON_LABELS = {"left": "links", "right": "rechts", "middle": "mitte"}


def _tuple2(value: Any, default: Tuple[float, float] = (0.0, 0.0)) -> Tuple[float, float]:
    try:
        return (float(value[0]), float(value[1]))
    except (TypeError, ValueError, IndexError):
        return default


@dataclass
class Anchor:
    """Gemerktes Aussehen einer Bildschirmstelle.

    ``template`` ist der enge Ausschnitt rund um den Klickpunkt, ``context``
    ein groesserer Ausschnitt der Umgebung, mit dem sich mehrere gleich
    aussehende Elemente unterscheiden lassen. ``hotspot`` ist die Lage des
    Klickpunktes innerhalb der Schablone (in Schablonen-Pixeln).
    """

    template: str = ""
    size: Tuple[int, int] = (0, 0)
    hotspot: Tuple[float, float] = (0.0, 0.0)
    context: str = ""
    context_size: Tuple[int, int] = (0, 0)
    context_hotspot: Tuple[float, float] = (0.0, 0.0)
    point: Tuple[float, float] = (0.0, 0.0)
    display_id: int = 0
    scale: float = 2.0
    threshold: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        for key in ("size", "hotspot", "context_size", "context_hotspot", "point"):
            data[key] = list(data[key])
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Anchor":
        return cls(
            template=str(data.get("template", "")),
            size=tuple(int(v) for v in _tuple2(data.get("size"))),
            hotspot=_tuple2(data.get("hotspot")),
            context=str(data.get("context", "")),
            context_size=tuple(int(v) for v in _tuple2(data.get("context_size"))),
            context_hotspot=_tuple2(data.get("context_hotspot")),
            point=_tuple2(data.get("point")),
            display_id=int(data.get("display_id", 0)),
            scale=float(data.get("scale", 2.0)),
            threshold=(None if data.get("threshold") in (None, "") else float(data["threshold"])),
        )


@dataclass
class Step:
    """Ein einzelner aufgenommener Vorgang."""

    kind: str
    delay_before: float = 0.0
    anchor: Optional[Anchor] = None
    anchor_to: Optional[Anchor] = None
    button: str = "left"
    clicks: int = 1
    modifiers: List[str] = field(default_factory=list)
    text: str = ""
    key: str = ""
    dx: float = 0.0
    dy: float = 0.0
    seconds: float = 0.0
    mode: str = "appear"
    timeout: Optional[float] = None
    on_error: str = ON_ERROR_ABORT
    enabled: bool = True
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "kind": self.kind,
            "delay_before": round(float(self.delay_before), 3),
            "on_error": self.on_error,
            "enabled": bool(self.enabled),
        }
        if self.anchor is not None:
            data["anchor"] = self.anchor.to_dict()
        if self.anchor_to is not None:
            data["anchor_to"] = self.anchor_to.to_dict()
        if self.kind in (CLICK, DRAG):
            data["button"] = self.button
        if self.kind == CLICK:
            data["clicks"] = int(self.clicks)
        if self.modifiers:
            data["modifiers"] = list(self.modifiers)
        if self.kind == TEXT:
            data["text"] = self.text
        if self.kind == KEY:
            data["key"] = self.key
        if self.kind == SCROLL:
            data["dx"] = self.dx
            data["dy"] = self.dy
        if self.kind == WAIT:
            data["seconds"] = round(float(self.seconds), 3)
        if self.kind == WAIT_IMAGE:
            data["mode"] = self.mode
        if self.timeout is not None:
            data["timeout"] = float(self.timeout)
        if self.note:
            data["note"] = self.note
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Step":
        anchor = data.get("anchor")
        anchor_to = data.get("anchor_to")
        timeout = data.get("timeout")
        return cls(
            kind=str(data.get("kind", CLICK)),
            delay_before=float(data.get("delay_before", 0.0)),
            anchor=Anchor.from_dict(anchor) if isinstance(anchor, dict) else None,
            anchor_to=Anchor.from_dict(anchor_to) if isinstance(anchor_to, dict) else None,
            button=str(data.get("button", "left")),
            clicks=int(data.get("clicks", 1)),
            modifiers=list(data.get("modifiers", []) or []),
            text=str(data.get("text", "")),
            key=str(data.get("key", "")),
            dx=float(data.get("dx", 0.0)),
            dy=float(data.get("dy", 0.0)),
            seconds=float(data.get("seconds", 0.0)),
            mode=str(data.get("mode", "appear")),
            timeout=(None if timeout in (None, "") else float(timeout)),
            on_error=str(data.get("on_error", ON_ERROR_ABORT)),
            enabled=bool(data.get("enabled", True)),
            note=str(data.get("note", "")),
        )

    def describe(self) -> str:
        """Kurzbeschreibung fuer die Schrittliste im Editor."""
        if self.kind == CLICK:
            what = {1: "Klick", 2: "Doppelklick", 3: "Dreifachklick"}.get(self.clicks, f"{self.clicks}x Klick")
            side = BUTTON_LABELS.get(self.button, self.button)
            extra = f" [{'+'.join(self.modifiers)}]" if self.modifiers else ""
            return f"{what} ({side}){extra}"
        if self.kind == DRAG:
            return "Ziehen (gedrueckt halten und bewegen)"
        if self.kind == SCROLL:
            direction = "hoch" if self.dy > 0 else "runter" if self.dy < 0 else ("links" if self.dx < 0 else "rechts")
            return f"Scrollen {direction} ({abs(self.dy) or abs(self.dx):.0f})"
        if self.kind == TEXT:
            shown = self.text if len(self.text) <= 40 else self.text[:37] + "..."
            return f'Text eingeben: "{shown}"'
        if self.kind == KEY:
            combo = "+".join(list(self.modifiers) + [self.key])
            return f"Taste: {combo}"
        if self.kind == WAIT:
            return f"Warten: {self.seconds:.1f} s"
        if self.kind == WAIT_IMAGE:
            return "Warten bis Element erscheint" if self.mode == "appear" else "Warten bis Element verschwindet"
        return self.kind

    @property
    def uses_anchor(self) -> bool:
        return self.kind in (CLICK, DRAG, SCROLL, WAIT_IMAGE)


@dataclass
class Macro:
    """Ein Button auf der Oberflaeche samt aufgenommener Schrittfolge."""

    name: str
    steps: List[Step] = field(default_factory=list)
    slug: str = ""
    hotkey: str = ""
    speed: float = 1.0
    threshold: Optional[float] = None
    created_at: str = ""
    updated_at: str = ""
    note: str = ""
    repeat: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "hotkey": self.hotkey,
            "speed": float(self.speed),
            "threshold": self.threshold,
            "created_at": self.created_at or datetime.now().isoformat(timespec="seconds"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "note": self.note,
            "repeat": int(self.repeat),
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], slug: str = "") -> "Macro":
        threshold = data.get("threshold")
        return cls(
            name=str(data.get("name", slug or "Unbenannt")),
            steps=[Step.from_dict(item) for item in data.get("steps", []) if isinstance(item, dict)],
            slug=slug,
            hotkey=str(data.get("hotkey", "")),
            speed=float(data.get("speed", 1.0) or 1.0),
            threshold=(None if threshold in (None, "") else float(threshold)),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            note=str(data.get("note", "")),
            repeat=int(data.get("repeat", 1) or 1),
        )

    def asset_names(self) -> List[str]:
        names: List[str] = []
        for step in self.steps:
            for anchor in (step.anchor, step.anchor_to):
                if anchor is None:
                    continue
                names.extend(name for name in (anchor.template, anchor.context) if name)
        return names
