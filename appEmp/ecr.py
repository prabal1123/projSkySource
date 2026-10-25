"""
PF ECR text file (Payroll Phase 7b).

One line per member for the locked payroll of a month, eleven fields separated
by "#~#" and no header line (EPFO ECR 2.0 layout; check a test file against
the EPFO portal before filing). Amounts are whole rupees. Members who paid PF
but have no valid 12 digit UAN are left out and reported.
EPF, EPS and EDLI wages all use the PF wage base of the record, so the
contributions in the file match what payroll worked out. How the EPS wage
ceiling applies is an open question for the CA.
"""
import re
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0")
SEP = "#~#"
UAN_RE = re.compile(r"^[0-9]{12}$")


def _whole(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _member_name(employee):
    user = employee.user
    name = (user.get_full_name() or user.get_username()).strip()
    return re.sub(r"[#~\r\n]+", " ", name)


def split_for_ecr(records):
    """
    Returns (included, left_out).
    included: list of (record, details dict); left_out: list of (name, reason).
    Records with no PF this month are skipped without a message.
    """
    included = []
    left_out = []
    for record in records:
        if record.pf <= ZERO and record.employer_eps <= ZERO and record.employer_epf <= ZERO:
            continue
        employee = record.employee
        name = _member_name(employee)
        uan = re.sub(r"\s+", "", employee.uan_no or "")
        if not uan:
            left_out.append((name, "UAN is missing"))
        elif not UAN_RE.match(uan):
            left_out.append((name, "UAN looks invalid (it should be 12 digits)"))
        else:
            included.append((record, {"name": name, "uan": uan}))
    return included, left_out


def ecr_line(record, details):
    base = _whole(record.pf_wage_base)
    ncp = max(0, _whole(Decimal(record.days_in_period) - Decimal(record.payable_days)))
    fields = [
        details["uan"],
        details["name"],
        _whole(record.gross_earned),
        base,
        base,
        base,
        _whole(record.pf),
        _whole(record.employer_eps),
        max(0, _whole(record.pf) - _whole(record.employer_eps)),
        ncp,
        0,
    ]
    return SEP.join(str(f) for f in fields)
