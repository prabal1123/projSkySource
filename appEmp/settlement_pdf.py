"""
Final settlement statement PDF (Payroll Phase 8a), built with ReportLab.
Only approved or paid settlements are printed.
"""
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .payslip_pdf import GRID, MUTED, NAVY, ROSE, TEAL, _employee_name, _inr


def build_settlement_pdf(settlement, reference=None):
    buffer = BytesIO()
    employee = settlement.employee
    exit_request = settlement.exit_request
    name = _employee_name(employee)
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"Final settlement - {name}",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=styles["Heading1"], textColor=NAVY, fontSize=18)
    small = ParagraphStyle("s", parent=styles["Normal"], fontSize=9, textColor=MUTED)

    last = exit_request.final_last_working_date or exit_request.proposed_last_working_date
    last_text = f"{last:%d %b %Y}" if last else "-"
    elements = [
        Paragraph(escape(settlement.organization.name), small),
        Paragraph("Full and Final Settlement", title),
        Paragraph(
            escape(f"{name} - {exit_request.get_exit_type_display()} - last working day {last_text}"),
            small,
        ),
        Spacer(1, 6 * mm),
    ]

    rows = [["Particulars", "Type", "Amount (INR)"]]
    for item in settlement.items.all():
        kind = "Earning" if item.kind == "EARNING" else "Deduction"
        label = item.label + (f" ({item.note})" if item.note else "")
        rows.append([label, kind, _inr(item.amount)])
    table = Table(rows, colWidths=[100 * mm, 28 * mm, 42 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
    ]))
    elements += [table, Spacer(1, 5 * mm)]

    net = settlement.net_payable
    totals = [
        ["Total earnings", _inr(settlement.total_earnings)],
        ["Total deductions", _inr(settlement.total_deductions)],
        ["Recoverable from employee" if net < 0 else "Net payable", f"Rs. {_inr(abs(net))}"],
    ]
    totals_table = Table(totals, colWidths=[128 * mm, 42 * mm])
    totals_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BACKGROUND", (0, 2), (-1, 2), ROSE if net < 0 else TEAL),
        ("TEXTCOLOR", (0, 2), (-1, 2), colors.white),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
    ]))
    elements += [totals_table, Spacer(1, 5 * mm)]

    if reference:
        if reference["locked"]:
            text = (
                f"Final month salary for {reference['label']} (Rs. {_inr(reference['net_pay'])}) "
                "is paid through payroll and is not part of this settlement."
            )
        else:
            text = (
                f"Final month salary for {reference['label']} is paid through payroll "
                "and is not part of this settlement."
            )
        elements += [Paragraph(escape(text), small), Spacer(1, 12 * mm)]
    else:
        elements.append(Spacer(1, 12 * mm))

    sign = Table(
        [["______________________", "______________________"],
         ["HR / Authorised signatory", "Employee signature"]],
        colWidths=[85 * mm, 85 * mm],
    )
    sign.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 1), (-1, 1), MUTED),
    ]))
    elements += [sign, Spacer(1, 8 * mm)]
    approved = f"{settlement.approved_at:%d %b %Y}" if settlement.approved_at else "-"
    elements.append(Paragraph(
        escape(f"System-generated statement. Approved on {approved}. Status: {settlement.get_status_display()}."),
        small,
    ))
    doc.build(elements)
    buffer.seek(0)
    return buffer
