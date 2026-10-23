"""
PDF output for payroll (Payroll Phase 4), built with ReportLab.

Both builders read ONLY from locked PayrollRecord rows, so a payslip can never
differ from what HR finalised, even if attendance or salary changed later.
"""
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .payroll_service import earned_components, earned_split

NAVY = colors.HexColor("#0F172A")
TEAL = colors.HexColor("#0F9E96")
ROSE = colors.HexColor("#9F1239")
GRID = colors.HexColor("#CBD5E1")
SOFT = colors.HexColor("#F1F5F9")
MUTED = colors.HexColor("#64748B")

ZERO = Decimal("0")


def _inr(value):
    return f"{value:,.2f}"


def _days(value):
    """22.0 -> '22', 29.5 -> '29.5'."""
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _employee_name(employee):
    return employee.user.get_full_name() or employee.user.username


def _employer_rows(record):
    """Rows for the employer-contribution block; empty if there is nothing to show."""
    items = [
        ("Employer PF - EPS", record.employer_eps),
        ("Employer PF - EPF", record.employer_epf),
        ("Employer EDLI", record.employer_edli),
        ("PF admin charges", record.employer_pf_admin),
        ("Employer ESI", record.employer_esi),
    ]
    rows = [[label, _inr(value)] for label, value in items if value > ZERO]
    if not rows:
        return []
    return (
        [["Employer contributions (not deducted from pay)", "Amount (INR)"]]
        + rows
        + [["Total Employer Contribution", _inr(record.employer_contribution_total)]]
    )


def build_payslip_pdf(record, compress=True):
    """
    Payslip for one LOCKED PayrollRecord. Returns a BytesIO positioned at 0.
    Raises ValueError for a record that is not locked.
    compress=False keeps page text readable in the raw bytes (used by tests).
    """
    if not record.is_locked:
        raise ValueError("A payslip can only be built from a locked payroll record.")

    employee = record.employee
    basic_earned, hra_earned = earned_split(record)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=18 * mm, bottomMargin=18 * mm, leftMargin=20 * mm, rightMargin=20 * mm,
        title=f"Payslip {record.period_label} - {_employee_name(employee)}",
        pageCompression=1 if compress else 0,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("SlipTitle", parent=styles["Heading1"], textColor=NAVY, spaceAfter=2)
    org_style = ParagraphStyle("SlipOrg", parent=styles["Normal"], textColor=TEAL, fontName="Helvetica-Bold")

    elements = [
        Paragraph(escape(record.organization.name), org_style),
        Paragraph("Payslip", title_style),
        Paragraph(
            f"{record.period_label} &nbsp;-&nbsp; "
            f"{record.period_start:%d %b %Y} to {record.period_end:%d %b %Y}",
            styles["Normal"],
        ),
        Spacer(1, 6 * mm),
    ]

    designation = str(employee.designation) if employee.designation_id else "-"
    joined = employee.date_hired.strftime("%d %b %Y") if employee.date_hired else "-"
    info = [
        ["Employee Name", _employee_name(employee), "Employee ID", str(employee.uuid)[:8].upper()],
        ["Designation", designation, "Date of Joining", joined],
    ]
    t_info = Table(info, colWidths=[32 * mm, 58 * mm, 32 * mm, 48 * mm])
    t_info.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TEXTCOLOR", (0, 0), (0, -1), TEAL),
        ("TEXTCOLOR", (2, 0), (2, -1), TEAL),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
    ]))
    elements += [t_info, Spacer(1, 5 * mm)]

    attendance = [
        ["Days in month", "Weekly offs", "Holidays", "Present", "Paid leave", "Loss of pay", "Payable days"],
        [
            str(record.days_in_period), str(record.weekly_off_days), str(record.holiday_days),
            _days(record.present_days), _days(record.paid_leave_days), _days(record.lop_days),
            _days(record.payable_days),
        ],
    ]
    t_att = Table(attendance, colWidths=[24 * mm] * 7)
    t_att.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), SOFT),
        ("TEXTCOLOR", (0, 0), (-1, 0), NAVY),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (-1, 1), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7.5),
        ("FONTSIZE", (0, 1), (-1, 1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements += [t_att, Spacer(1, 6 * mm)]

    parts = earned_components(record)
    earnings = [
        ["Earnings", "Amount (INR)"],
        ["Basic Salary", _inr(basic_earned)],
    ]
    if record.da > ZERO:
        earnings.append(["Dearness Allowance (DA)", _inr(parts["da"])])
    earnings.append(["HRA", _inr(hra_earned)])
    if record.special_allowance > ZERO:
        earnings.append(["Special Allowance", _inr(parts["special"])])
    if record.other_allowances > ZERO:
        earnings.append(["Other Allowances", _inr(parts["other"])])
    earnings.append(["Gross Earnings", _inr(record.gross_earned)])
    if record.statutory_wages > ZERO and record.statutory_wages != record.gross_earned and record.pf > ZERO:
        earnings.append([f"(PF calculated on statutory wages of {_inr(record.statutory_wages)})", ""])
    prorated = record.payable_days != Decimal(record.days_in_period)
    if prorated:
        earnings.append([
            f"(Pro-rated: {_days(record.payable_days)} of {record.days_in_period} days; "
            f"full month {_inr(record.gross_monthly)})",
            "",
        ])
    deductions = [
        ["Deductions", "Amount (INR)"],
        ["Provident Fund (PF)", _inr(record.pf)],
        ["ESI", _inr(record.esi)],
        ["Other Deductions", _inr(record.other_deductions)],
        ["TDS (Tax Deducted at Source)", _inr(record.tds)],
        ["Total Deductions", _inr(record.total_deductions)],
    ]

    def block(rows, header_color):
        table = Table(rows, colWidths=[120 * mm, 50 * mm])
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), header_color),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("GRID", (0, 0), (-1, -1), 0.5, GRID),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ]
        for i, row in enumerate(rows):
            if row[0] in ("Gross Earnings", "Total Deductions", "Total Employer Contribution"):
                style.append(("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"))
            if row[0].startswith("("):
                style += [
                    ("FONTSIZE", (0, i), (-1, i), 8),
                    ("FONTNAME", (0, i), (-1, i), "Helvetica-Oblique"),
                    ("TEXTCOLOR", (0, i), (-1, i), MUTED),
                    ("SPAN", (0, i), (-1, i)),
                ]
        table.setStyle(TableStyle(style))
        return table

    elements += [block(earnings, NAVY), Spacer(1, 5 * mm), block(deductions, ROSE), Spacer(1, 6 * mm)]

    net_table = Table([["Net Pay", f"Rs. {_inr(record.net_pay)}"]], colWidths=[120 * mm, 50 * mm])
    net_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), TEAL),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 12),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    elements.append(net_table)

    employer_rows = _employer_rows(record)
    if employer_rows:
        elements += [Spacer(1, 6 * mm), block(employer_rows, MUTED)]

    if record.mode_of_payment or record.payment_date:
        paid_bits = []
        if record.mode_of_payment:
            paid_bits.append(f"Mode of payment: {escape(record.mode_of_payment)}")
        if record.payment_date:
            paid_bits.append(f"Payment date: {record.payment_date:%d %b %Y}")
        elements += [Spacer(1, 4 * mm), Paragraph(" &nbsp;-&nbsp; ".join(paid_bits), styles["Normal"])]

    finalised = record.locked_at.strftime("%d %b %Y") if record.locked_at else "-"
    elements += [
        Spacer(1, 10 * mm),
        Paragraph(
            f"This is a system-generated payslip, finalised on {finalised}. "
            "Tax figures are an estimate; refer to Form 16 issued by HR for the final tax liability.",
            styles["Italic"],
        ),
    ]

    doc.build(elements)
    buffer.seek(0)
    return buffer


def build_payroll_summary_pdf(records, organization_name, year, month, project_label="All projects"):
    """
    Register of locked payroll for one month (landscape A4, header repeats on
    every page). `records` must be locked PayrollRecords with employee, user
    and designation already loaded.
    """
    records = list(records)
    for r in records:
        if not r.is_locked:
            raise ValueError("The payroll summary can only include locked records.")
    period_label = records[0].period_label if records else f"{year}-{month:02d}"

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        topMargin=14 * mm, bottomMargin=14 * mm, leftMargin=12 * mm, rightMargin=12 * mm,
        title=f"Payroll summary {period_label}",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("SumTitle", parent=styles["Heading1"], textColor=NAVY, spaceAfter=2)
    elements = [
        Paragraph(f"Payroll Summary - {period_label}", title_style),
        Paragraph(
            f"{escape(organization_name)} &nbsp;-&nbsp; {escape(project_label)} &nbsp;-&nbsp; "
            f"{len(records)} employee{'s' if len(records) != 1 else ''} (locked payroll only)",
            styles["Normal"],
        ),
        Spacer(1, 5 * mm),
    ]

    header = [
        "Employee", "Designation", "Payable\ndays", "LOP\ndays",
        "Gross earned", "PF", "ESI", "Other", "TDS", "Net pay",
    ]
    rows = [header]
    totals = {k: ZERO for k in ("gross", "pf", "esi", "other", "tds", "net")}
    for r in records:
        rows.append([
            _employee_name(r.employee),
            str(r.employee.designation) if r.employee.designation_id else "-",
            _days(r.payable_days), _days(r.lop_days),
            _inr(r.gross_earned), _inr(r.pf), _inr(r.esi), _inr(r.other_deductions),
            _inr(r.tds), _inr(r.net_pay),
        ])
        totals["gross"] += r.gross_earned
        totals["pf"] += r.pf
        totals["esi"] += r.esi
        totals["other"] += r.other_deductions
        totals["tds"] += r.tds
        totals["net"] += r.net_pay
    rows.append([
        "Total", "", "", "", _inr(totals["gross"]), _inr(totals["pf"]), _inr(totals["esi"]),
        _inr(totals["other"]), _inr(totals["tds"]), _inr(totals["net"]),
    ])

    table = Table(
        rows, repeatRows=1,
        colWidths=[48 * mm, 38 * mm, 16 * mm, 14 * mm, 28 * mm, 22 * mm, 20 * mm, 20 * mm, 22 * mm, 30 * mm],
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, GRID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, SOFT]),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, -1), (-1, -1), TEAL),
        ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)
    return buffer
