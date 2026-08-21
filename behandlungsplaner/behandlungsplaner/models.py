"""Datenmodell fuer einen Behandlungsplan: einzelne Planungspositionen
(PlanItem) auf einem OPG sowie der Gesamtplan (TreatmentPlan).

Alle Positions- und Groessenangaben werden als Anteil der Bildbreite/-hoehe
(0..1) gespeichert, damit der Plan unabhaengig von Zoomstufe und
Bildaufloesung reproduzierbar bleibt.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from .fdi import is_valid_fdi

# ---------------------------------------------------------------- Befundarten
KIND_IMPLANTAT = "implantat"
KIND_KRONE = "krone"
KIND_TEILKRONE = "teilkrone"
KIND_NICO_FDOK = "nico_fdok"
KIND_EXTRAKTION = "extraktion"
KIND_WURZELBEHANDLUNG = "wurzelbehandlung"
KIND_FEHLENDER_ZAHN = "fehlender_zahn"
KIND_BRUECKE = "bruecke"

ALL_KINDS = [
    KIND_IMPLANTAT,
    KIND_KRONE,
    KIND_TEILKRONE,
    KIND_NICO_FDOK,
    KIND_EXTRAKTION,
    KIND_WURZELBEHANDLUNG,
    KIND_FEHLENDER_ZAHN,
    KIND_BRUECKE,
]

KIND_LABELS = {
    KIND_IMPLANTAT: "Implantat",
    KIND_KRONE: "Krone",
    KIND_TEILKRONE: "Teilkrone",
    KIND_NICO_FDOK: "NICO/FDOK",
    KIND_EXTRAKTION: "Extraktion",
    KIND_WURZELBEHANDLUNG: "Wurzelbehandlung",
    KIND_FEHLENDER_ZAHN: "Fehlender Zahn",
    KIND_BRUECKE: "Bruecke",
}

# "tooth"   = an genau einem Zahn verankert
# "region"  = frei im Kiefer platzierbar, nicht zwingend zahngebunden
# "span"    = verbindet zwei (oder mehr) Zahnpositionen
KIND_ANCHOR_TYPE = {
    KIND_IMPLANTAT: "tooth",
    KIND_KRONE: "tooth",
    KIND_TEILKRONE: "tooth",
    KIND_NICO_FDOK: "region",
    KIND_EXTRAKTION: "tooth",
    KIND_WURZELBEHANDLUNG: "tooth",
    KIND_FEHLENDER_ZAHN: "tooth",
    KIND_BRUECKE: "span",
}

# Beispielhafte Standardkosten (EUR) als Ausgangswert - KEINE verbindliche
# GOZ-/BEMA-Abrechnungsgrundlage, in den Einstellungen frei anpassbar und pro
# Position jederzeit ueberschreibbar.
DEFAULT_PRICE_LIST = {
    KIND_IMPLANTAT: 1800.0,
    KIND_KRONE: 650.0,
    KIND_TEILKRONE: 480.0,
    KIND_NICO_FDOK: 0.0,
    KIND_EXTRAKTION: 90.0,
    KIND_WURZELBEHANDLUNG: 450.0,
    KIND_FEHLENDER_ZAHN: 0.0,
    KIND_BRUECKE: 1200.0,
}

STATUS_GEPLANT = "geplant"
STATUS_DURCHGEFUEHRT = "durchgefuehrt"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _today_iso() -> str:
    return date.today().isoformat()


def new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class PlanItem:
    kind: str
    x: float
    y: float
    width: float
    height: float
    id: str = field(default_factory=new_id)
    rotation: float = 0.0
    fdi_tooth: Optional[int] = None
    # Nur fuer KIND_BRUECKE: Endpunkt-Anker (zweite Position) sowie optional
    # die Liste der ueberspannten FDI-Zahnnummern (Pfeiler + Zwischenglieder).
    end_x: Optional[float] = None
    end_y: Optional[float] = None
    bridge_teeth: Optional[list] = None
    status: str = STATUS_GEPLANT
    planned_date: str = field(default_factory=_today_iso)
    done_date: Optional[str] = None
    cost: float = 0.0
    note: str = ""
    service_code: str = ""
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def __post_init__(self):
        if self.kind not in ALL_KINDS:
            raise ValueError(f"Unbekannte Befundart: {self.kind}")
        if self.fdi_tooth is not None and not is_valid_fdi(self.fdi_tooth):
            raise ValueError(f"Ungueltige FDI-Zahnnummer: {self.fdi_tooth}")
        if self.status not in (STATUS_GEPLANT, STATUS_DURCHGEFUEHRT):
            raise ValueError(f"Unbekannter Status: {self.status}")

    @property
    def label(self) -> str:
        base = KIND_LABELS[self.kind]
        if self.kind == KIND_BRUECKE and self.bridge_teeth:
            return f"{base} ({self.bridge_teeth[0]}-{self.bridge_teeth[-1]})"
        if self.fdi_tooth is not None:
            return f"{base} (Zahn {self.fdi_tooth})"
        return f"{base} (nicht zugeordnet)"

    def mark_done(self, on: Optional[str] = None) -> None:
        self.status = STATUS_DURCHGEFUEHRT
        self.done_date = on or _today_iso()
        self.updated_at = _now_iso()

    def mark_planned(self) -> None:
        self.status = STATUS_GEPLANT
        self.done_date = None
        self.updated_at = _now_iso()

    def touch(self) -> None:
        self.updated_at = _now_iso()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "rotation": self.rotation,
            "fdi_tooth": self.fdi_tooth,
            "end_x": self.end_x,
            "end_y": self.end_y,
            "bridge_teeth": list(self.bridge_teeth) if self.bridge_teeth else None,
            "status": self.status,
            "planned_date": self.planned_date,
            "done_date": self.done_date,
            "cost": self.cost,
            "note": self.note,
            "service_code": self.service_code,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PlanItem":
        kwargs = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**kwargs)


@dataclass
class TreatmentPlan:
    schema_version: int = 1
    plan_id: str = field(default_factory=new_id)
    patient_name: str = ""
    patient_birthdate: Optional[str] = None
    practitioner: str = ""
    plan_date: str = field(default_factory=_today_iso)
    image_filename: str = ""
    image_width_px: int = 0
    image_height_px: int = 0
    calibration_enabled: bool = False
    # fdi_tooth -> (x, y) als Anteil der Bildbreite/-hoehe
    calibration_points: dict = field(default_factory=dict)
    items: list = field(default_factory=list)
    price_list: dict = field(default_factory=lambda: dict(DEFAULT_PRICE_LIST))
    general_note: str = ""
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def add_item(self, item: PlanItem) -> PlanItem:
        self.items.append(item)
        self.touch()
        return item

    def remove_item(self, item_id: str) -> bool:
        before = len(self.items)
        self.items = [i for i in self.items if i.id != item_id]
        removed = len(self.items) != before
        if removed:
            self.touch()
        return removed

    def get_item(self, item_id: str) -> Optional[PlanItem]:
        for item in self.items:
            if item.id == item_id:
                return item
        return None

    def touch(self) -> None:
        self.updated_at = _now_iso()

    def total_cost(self, status: Optional[str] = None) -> float:
        if status is None:
            return sum(i.cost for i in self.items)
        return sum(i.cost for i in self.items if i.status == status)

    def summary_by_kind(self) -> dict:
        summary = {}
        for item in self.items:
            entry = summary.setdefault(item.kind, {"count": 0, "cost": 0.0})
            entry["count"] += 1
            entry["cost"] += item.cost
        return summary

    def default_cost_for(self, kind: str) -> float:
        return self.price_list.get(kind, DEFAULT_PRICE_LIST.get(kind, 0.0))

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "patient_name": self.patient_name,
            "patient_birthdate": self.patient_birthdate,
            "practitioner": self.practitioner,
            "plan_date": self.plan_date,
            "image_filename": self.image_filename,
            "image_width_px": self.image_width_px,
            "image_height_px": self.image_height_px,
            "calibration_enabled": self.calibration_enabled,
            "calibration_points": {
                str(tooth): list(pos) for tooth, pos in self.calibration_points.items()
            },
            "items": [i.to_dict() for i in self.items],
            "price_list": dict(self.price_list),
            "general_note": self.general_note,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TreatmentPlan":
        kwargs = {k: v for k, v in data.items() if k in cls.__dataclass_fields__ and k != "items" and k != "calibration_points"}
        plan = cls(**kwargs)
        plan.calibration_points = {
            int(tooth): tuple(pos) for tooth, pos in data.get("calibration_points", {}).items()
        }
        plan.items = [PlanItem.from_dict(d) for d in data.get("items", [])]
        return plan
