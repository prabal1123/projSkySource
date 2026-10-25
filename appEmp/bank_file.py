"""
Bank payment file (Payroll Phase 7a).

A generic NEFT CSV for the locked payroll of one month: one line per employee
with the net pay, account number and IFSC. Employees whose bank details are
missing or malformed, or whose net pay is zero, are left out and reported so
HR can fix them. Text cells that could be read as a spreadsheet formula get a
leading apostrophe.
"""
import csv
import re
from decimal import Decimal

ZERO = Decimal("0")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
ACCOUNT_RE = re.compile(r"^[A-Za-z0-9]{6,30}$")

HEADER = [
    "Sr No", "Employee Name", "Account Number", "IFSC", "Bank Name",
    "Amount", "Narration", "Employee Ref",
]


def _safe(text):
    text = (text or "").strip()
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def _name(employee):
    user = employee.user
    return (user.get_full_name() or user.get_username()).strip()


def split_for_bank(records):
    """
    Returns (included, left_out).
    included: list of (record, details dict); left_out: list of (name, reason).
    """
    included = []
    left_out = []
    for record in records:
        employee = record.employee
        name = _name(employee)
        account = re.sub(r"\s+", "", employee.bank_account_no or "")
        ifsc = (employee.ifsc_no or "").strip().upper()
        if record.net_pay <= ZERO:
            left_out.append((name, "net pay is zero"))
        elif not account:
            left_out.append((name, "account number is missing"))
        elif not ACCOUNT_RE.match(account):
            left_out.append((name, "account number looks invalid"))
        elif not ifsc:
            left_out.append((name, "IFSC is missing"))
        elif not IFSC_RE.match(ifsc):
            left_out.append((name, "IFSC looks invalid"))
        else:
            included.append((record, {
                "name": name,
                "account": account,
                "ifsc": ifsc,
                "bank_name": (employee.bank_name or "").strip(),
                "ref": str(employee.uuid)[:8].upper(),
            }))
    return included, left_out


def write_bank_csv(fileobj, included, narration):
    writer = csv.writer(fileobj)
    writer.writerow(HEADER)
    for number, (record, d) in enumerate(included, start=1):
        writer.writerow([
            number,
            _safe(d["name"]),
            d["account"],
            d["ifsc"],
            _safe(d["bank_name"]),
            f"{record.net_pay:.2f}",
            _safe(narration),
            d["ref"],
        ])
