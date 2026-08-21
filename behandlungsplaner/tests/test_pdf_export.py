import pytest
from PIL import Image

pypdf = pytest.importorskip("pypdf")

from behandlungsplaner import pdf_export
from behandlungsplaner.models import KIND_BRUECKE, KIND_IMPLANTAT, KIND_KRONE, PlanItem, TreatmentPlan


def _sample_plan():
    plan = TreatmentPlan(
        patient_name="Erika Mustermann",
        patient_birthdate="1980-05-01",
        practitioner="Dr. Beispiel",
        plan_date="2026-08-21",
    )
    plan.add_item(PlanItem(kind=KIND_IMPLANTAT, x=0.2, y=0.3, width=0.05, height=0.08, fdi_tooth=36, cost=1800, note="Sinuslift noetig"))
    plan.add_item(PlanItem(kind=KIND_KRONE, x=0.3, y=0.3, width=0.05, height=0.06, fdi_tooth=37, cost=650))
    item = PlanItem(kind=KIND_IMPLANTAT, x=0.4, y=0.3, width=0.05, height=0.08, fdi_tooth=46, cost=1800)
    item.mark_done()
    plan.add_item(item)
    plan.add_item(PlanItem(
        kind=KIND_BRUECKE, x=0.5, y=0.3, width=0.1, height=0.02,
        end_x=0.6, end_y=0.3, bridge_teeth=[14, 15, 16], cost=1200,
    ))
    return plan


def test_export_pdf_creates_valid_multi_element_pdf(tmp_path):
    plan = _sample_plan()
    img = Image.new("RGB", (1200, 600), (90, 90, 90))
    dest = tmp_path / "plan.pdf"

    result_path = pdf_export.export_pdf(plan, img, dest, clinic_name="Zahnarztpraxis Beispiel")

    assert result_path == dest
    assert dest.exists()
    assert dest.stat().st_size > 1000

    reader = pypdf.PdfReader(str(dest))
    assert len(reader.pages) >= 1
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Erika Mustermann" in text
    assert "Zahnarztpraxis Beispiel" in text
    assert "Gesamtsumme" in text
    assert "5.450,00" in text.replace("\xa0", " ")  # 1800+650+1800+1200 (deutsches Format)


def test_export_pdf_without_clinic_name(tmp_path):
    plan = _sample_plan()
    plan_no_clinic = plan
    img = Image.new("RGB", (800, 400), (100, 100, 100))
    dest = tmp_path / "plan2.pdf"
    pdf_export.export_pdf(plan_no_clinic, img, dest)
    assert dest.exists()


def test_export_pdf_handles_empty_plan(tmp_path):
    plan = TreatmentPlan(patient_name="Ohne Befunde")
    img = Image.new("RGB", (400, 200), (100, 100, 100))
    dest = tmp_path / "empty.pdf"
    pdf_export.export_pdf(plan, img, dest)
    assert dest.exists()


def test_fmt_eur_uses_german_format():
    assert pdf_export._fmt_eur(1800) == "1.800,00 €"
    assert pdf_export._fmt_eur(0) == "0,00 €"
    assert pdf_export._fmt_eur(1234567.5) == "1.234.567,50 €"
