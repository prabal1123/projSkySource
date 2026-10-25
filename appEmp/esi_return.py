"""
ESI monthly contribution file (Payroll Phase 7c).

An Excel sheet with one row per insured person for the locked payroll of a
month, laid out like the ESIC monthly contribution template (check the headers
against the current template on the ESIC portal before uploading). Only people
with ESI wages or ESI deducted appear. Anyone without a valid 10 digit ESIC
number is left out and reported.

Days are the payable days rounded to whole days and wages are the ESI wage
base in whole rupees. Reason codes used when there are no paid days:
2 = left service (exit in this month), 1 = on leave; 0 otherwise.
"""
import io
import re
from decimal import ROUND_HALF_UP, Decimal

from openpyxl import Workbook

ZERO = Decimal("0")
IP_RE = re.compile(r"^[0-9]{10}$")

HEADER = [
    "IP Number",
    "IP Name",
    "No of Days for which wages paid/payable during the month",
    "Total Monthly Wages",
    "Reason Code for Zero workings days (numeric only; provide 0 for all other reasons)",
    "Last Working Day (DD/MM/YYYY)",
]


def _whole(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _safe(text):
    text = (text or "").strip()
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def _name(employee):
    user = employee.user
    return (user.get_full_name() or user.get_username()).strip()


def split_for_esi(records, exit_dates):
    """
    Returns (included, left_out).
    included: list of (record, details dict); left_out: list of (name, reason).
    exit_dates: {employee_id: final last working date}.
    Records with no ESI wages and no ESI are skipped without a message.
    """
    included = []
    left_out = []
    for record in records:
        if record.esi_wage_base <= ZERO and record.esi <= ZERO:
            continue
        employee = record.employee
        name = _name(employee)
        ip = re.sub(r"\s+", "", employee.esic_no or "")
        if not ip:
            left_out.append((name, "ESIC number is missing"))
            continue
        if not IP_RE.match(ip):
            left_out.append((name, "ESIC number looks invalid (it should be 10 digits)"))
            continue

        days = _whole(record.payable_days)
        last = exit_dates.get(employee.pk)
        last_text = ""
        if last and record.period_start <= last <= record.period_end:
            last_text = f"{last:%d/%m/%Y}"
        if days > 0:
            wages = _whole(record.esi_wage_base)
            reason = 0
        else:
            wages = 0
            reason = 2 if last_text else 1
        included.append((record, {
            "ip": ip, "name": name, "days": days, "wages": wages,
            "reason": reason, "last": last_text,
        }))
    return included, left_out


def build_esi_workbook(included):
    """The .xlsx file as bytes."""
    wb = Workbook()
    ws = wb.active
    ws.title = "ESI Return"
    ws.append(HEADER)
    for _record, d in included:
        ws.append([d["ip"], _safe(d["name"]), d["days"], d["wages"], d["reason"], d["last"]])
    for row in ws.iter_rows(min_row=2, max_col=1):
        for cell in row:
            cell.number_format = "@"
    for column, width in zip("ABCDEF", (16, 28, 22, 18, 22, 22)):
        ws.column_dimensions[column].width = width
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
