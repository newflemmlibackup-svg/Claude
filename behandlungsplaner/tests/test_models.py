import pytest

from behandlungsplaner import fdi
from behandlungsplaner.models import (
    DEFAULT_PRICE_LIST,
    KIND_BRUECKE,
    KIND_IMPLANTAT,
    KIND_KRONE,
    STATUS_DURCHGEFUEHRT,
    STATUS_GEPLANT,
    PlanItem,
    TreatmentPlan,
)


def test_fdi_basic():
    assert fdi.is_valid_fdi(18)
    assert fdi.is_valid_fdi(48)
    assert not fdi.is_valid_fdi(19)
    assert not fdi.is_valid_fdi(9)
    assert not fdi.is_valid_fdi(0)
    assert fdi.fdi_quadrant(36) == 3
    assert fdi.fdi_tooth_index(36) == 6
    assert fdi.fdi_arch(16) == "oben"
    assert fdi.fdi_arch(46) == "unten"
    assert fdi.fdi_side(18) == "rechts"
    assert fdi.fdi_side(28) == "links"
    assert fdi.fdi_tooth_class(11) == "schneidezahn"
    assert fdi.fdi_tooth_class(18) == "molar"
    assert len(fdi.ALL_FDI_TEETH) == 32
    assert len(set(fdi.ALL_FDI_TEETH)) == 32


def test_fdi_default_row_position():
    idx, row = fdi.default_row_position(18)
    assert idx == 0 and row == "oben"
    idx, row = fdi.default_row_position(28)
    assert idx == 15 and row == "oben"
    idx, row = fdi.default_row_position(48)
    assert idx == 0 and row == "unten"


def test_plan_item_defaults_and_validation():
    item = PlanItem(kind=KIND_IMPLANTAT, x=0.5, y=0.5, width=0.05, height=0.08, fdi_tooth=36)
    assert item.status == STATUS_GEPLANT
    assert item.id
    assert "Zahn 36" in item.label

    with pytest.raises(ValueError):
        PlanItem(kind="unbekannt", x=0, y=0, width=0.1, height=0.1)

    with pytest.raises(ValueError):
        PlanItem(kind=KIND_IMPLANTAT, x=0, y=0, width=0.1, height=0.1, fdi_tooth=99)


def test_plan_item_status_roundtrip():
    item = PlanItem(kind=KIND_KRONE, x=0.1, y=0.1, width=0.05, height=0.05, fdi_tooth=11)
    assert item.status == STATUS_GEPLANT
    item.mark_done()
    assert item.status == STATUS_DURCHGEFUEHRT
    assert item.done_date is not None
    item.mark_planned()
    assert item.status == STATUS_GEPLANT
    assert item.done_date is None


def test_plan_item_serialization_roundtrip():
    item = PlanItem(
        kind=KIND_BRUECKE,
        x=0.2, y=0.3, width=0.15, height=0.06,
        end_x=0.35, end_y=0.31,
        bridge_teeth=[14, 15, 16],
        cost=1500.0,
        note="Zirkonbruecke",
    )
    data = item.to_dict()
    restored = PlanItem.from_dict(data)
    assert restored.to_dict() == data
    assert restored.bridge_teeth == [14, 15, 16]


def test_treatment_plan_totals_and_summary():
    plan = TreatmentPlan(patient_name="Mustermann, Erika")
    plan.add_item(PlanItem(kind=KIND_IMPLANTAT, x=0.1, y=0.1, width=0.05, height=0.08, fdi_tooth=16, cost=1800))
    i2 = plan.add_item(PlanItem(kind=KIND_KRONE, x=0.2, y=0.1, width=0.05, height=0.06, fdi_tooth=17, cost=650))
    plan.add_item(PlanItem(kind=KIND_KRONE, x=0.3, y=0.1, width=0.05, height=0.06, fdi_tooth=26, cost=650))

    assert plan.total_cost() == 1800 + 650 + 650
    assert plan.total_cost(status=STATUS_GEPLANT) == 1800 + 650 + 650

    i2.mark_done()
    assert plan.total_cost(status=STATUS_DURCHGEFUEHRT) == 650
    assert plan.total_cost(status=STATUS_GEPLANT) == 1800 + 650

    summary = plan.summary_by_kind()
    assert summary[KIND_IMPLANTAT] == {"count": 1, "cost": 1800.0}
    assert summary[KIND_KRONE] == {"count": 2, "cost": 1300.0}

    assert plan.remove_item(i2.id) is True
    assert len(plan.items) == 2
    assert plan.remove_item("nicht-vorhanden") is False


def test_treatment_plan_default_cost_uses_price_list_then_fallback():
    plan = TreatmentPlan()
    assert plan.default_cost_for(KIND_IMPLANTAT) == DEFAULT_PRICE_LIST[KIND_IMPLANTAT]
    plan.price_list[KIND_IMPLANTAT] = 2200.0
    assert plan.default_cost_for(KIND_IMPLANTAT) == 2200.0


def test_treatment_plan_serialization_roundtrip():
    plan = TreatmentPlan(
        patient_name="Mustermann, Erika",
        patient_birthdate="1980-05-01",
        practitioner="Dr. Beispiel",
        image_filename="opg.png",
        image_width_px=3000,
        image_height_px=1400,
    )
    plan.calibration_enabled = True
    plan.calibration_points = {18: (0.05, 0.2), 11: (0.45, 0.35)}
    plan.add_item(PlanItem(kind=KIND_IMPLANTAT, x=0.1, y=0.2, width=0.05, height=0.08, fdi_tooth=16, cost=1800))

    data = plan.to_dict()
    restored = TreatmentPlan.from_dict(data)

    assert restored.patient_name == plan.patient_name
    assert restored.calibration_points == {18: (0.05, 0.2), 11: (0.45, 0.35)}
    assert len(restored.items) == 1
    assert restored.items[0].fdi_tooth == 16
    assert restored.to_dict() == data
