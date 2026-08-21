"""Erstellt ein PDF-Dokument aus einem Behandlungsplan: Kopfdaten, das
annotierte OPG-Bild, eine Legende der verwendeten Symbole sowie eine
Kostentabelle mit Zwischensummen.
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from . import render, shapes
from .fdi import fdi_label
from .models import STATUS_DURCHGEFUEHRT, STATUS_GEPLANT, TreatmentPlan

DISCLAIMER = (
    "Diese Darstellung dient der internen Behandlungsuebersicht und -planung. "
    "Zahnpositionen und Symbolgroessen basieren auf manueller bzw. "
    "kalibrierter Einzeichnung, nicht auf einer automatischen Bildanalyse. "
    "Kostenangaben sind unverbindliche Praxis-Schaetzwerte und ersetzen "
    "keinen amtlichen Heil- und Kostenplan."
)


def _fmt_eur(value: float) -> str:
    s = f"{value:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €"


def _pil_to_flowable(img: Image.Image, max_width_mm: float) -> RLImage:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    max_width = max_width_mm * mm
    scale = min(1.0, max_width / img.width)
    return RLImage(buf, width=img.width * scale, height=img.height * scale)


def _item_sort_key(item):
    return (0 if item.fdi_tooth is None else 1, item.fdi_tooth or 0, item.kind)


def export_pdf(plan: TreatmentPlan, image: Image.Image, dest_path, *,
                clinic_name: str = "", show_calibration: bool = False) -> Path:
    dest_path = Path(dest_path)
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        str(dest_path), pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Behandlungsplan {plan.patient_name}".strip(),
    )
    story = []

    title = clinic_name.strip() or "Behandlungsplan"
    story.append(Paragraph(title, styles["Title"]))
    if clinic_name.strip():
        story.append(Paragraph("Behandlungsplan", styles["Heading2"]))
    story.append(Spacer(1, 4 * mm))

    header_rows = [
        ["Patient/-in:", plan.patient_name or "-", "Geburtsdatum:", plan.patient_birthdate or "-"],
        ["Behandler/-in:", plan.practitioner or "-", "Datum:", plan.plan_date or "-"],
    ]
    header_table = Table(header_rows, colWidths=[30 * mm, 65 * mm, 30 * mm, 45 * mm])
    header_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 6 * mm))

    annotated = render.render_plan(plan, image, show_calibration=show_calibration)
    story.append(_pil_to_flowable(annotated, max_width_mm=180))
    story.append(Spacer(1, 4 * mm))

    used_kinds = {item.kind for item in plan.items}
    legend_entries = [e for e in shapes.legend_entries() if e[0] in used_kinds]
    if legend_entries:
        legend_rows = []
        row = []
        for idx, (_kind, label, color_hex) in enumerate(legend_entries):
            row.append(f"■ {label}")
            if len(row) == 3:
                legend_rows.append(row)
                row = []
        if row:
            legend_rows.append(row)
        legend_table = Table(legend_rows, colWidths=[60 * mm] * 3)
        style_cmds = [("FONTSIZE", (0, 0), (-1, -1), 8)]
        for idx, (_kind, _label, color_hex) in enumerate(legend_entries):
            r, c = divmod(idx, 3)
            style_cmds.append(("TEXTCOLOR", (c, r), (c, r), colors.HexColor(color_hex)))
        legend_table.setStyle(TableStyle(style_cmds))
        story.append(legend_table)
        story.append(Spacer(1, 6 * mm))

    story.append(Paragraph("Planungsliste", styles["Heading2"]))
    table_data = [["Typ", "Zahn (FDI)", "Status", "Datum", "Notiz", "Kosten"]]
    for item in sorted(plan.items, key=_item_sort_key):
        tooth_text = "-"
        if item.bridge_teeth:
            tooth_text = f"{item.bridge_teeth[0]}–{item.bridge_teeth[-1]}"
        elif item.fdi_tooth is not None:
            tooth_text = str(item.fdi_tooth)
        status_text = "durchgeführt" if item.status == STATUS_DURCHGEFUEHRT else "geplant"
        date_text = item.done_date if item.status == STATUS_DURCHGEFUEHRT and item.done_date else item.planned_date
        table_data.append([
            item.label.split(" (")[0],
            tooth_text,
            status_text,
            date_text or "-",
            item.note or "",
            _fmt_eur(item.cost),
        ])

    cost_table = Table(table_data, colWidths=[32 * mm, 22 * mm, 24 * mm, 22 * mm, 50 * mm, 25 * mm], repeatRows=1)
    cost_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("ALIGN", (5, 0), (5, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(cost_table)
    story.append(Spacer(1, 4 * mm))

    total_all = plan.total_cost()
    total_open = plan.total_cost(status=STATUS_GEPLANT)
    total_done = plan.total_cost(status=STATUS_DURCHGEFUEHRT)
    summary_rows = [
        ["Summe geplant (offen):", _fmt_eur(total_open)],
        ["Summe durchgeführt:", _fmt_eur(total_done)],
        ["Gesamtsumme:", _fmt_eur(total_all)],
    ]
    summary_table = Table(summary_rows, colWidths=[50 * mm, 30 * mm])
    summary_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    story.append(summary_table)

    if plan.general_note.strip():
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Allgemeine Notiz", styles["Heading3"]))
        story.append(Paragraph(plan.general_note.strip(), styles["BodyText"]))

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(DISCLAIMER, styles["Italic"]))

    doc.build(story)
    return dest_path
