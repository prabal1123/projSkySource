"""
Payroll calculation service (Payroll Phase 2).

Computes one month of payroll for MONTHLY-wage employees from the records the
app already keeps: Salary, WorkSchedule, Attendance, approved LeaveRequest,
mandatory/optional Holiday and (for joiners/leavers) date_hired and the final
last working date of a completed exit.

DAILY-wage staff are not handled here; they stay on the wage register.

How a day is classified (first match wins)
------------------------------------------
1. Before joining / after the final working day  -> not employed (not payable)
2. Weekly off per the employee's WorkSchedule      -> paid
3. Mandatory holiday, or approved optional holiday -> paid
4. Approved full-day leave                         -> paid or loss-of-pay, per
                                                      LeaveTypeMaster.is_paid
5. Approved half-day leave                         -> that half paid/LOP; the
                                                      other half follows 6-8
6. Attendance PRESENT / LATE                       -> paid
   Attendance HALF_DAY                             -> 0.5 paid, 0.5 loss-of-pay
   Attendance LEAVE (no approved request)          -> paid leave, with warning
   Attendance ABSENT                               -> loss-of-pay
7. No record, day not yet over (after `as_of`)     -> assumed payable; the month
                                                      is flagged provisional
8. No record, day already over                     -> absent, loss-of-pay

Money
-----
payable_days = days employed in the month - loss-of-pay days
gross_earned = gross_monthly x payable_days / days_in_month
PF and ESI follow the employee's statutory profile (Auto / Fixed / Not applicable);
the employer's share is calculated too. Other deductions are the fixed monthly
amount on the Salary.
TDS is projected for the whole financial year (April to March) and spread over
the months left (see appEmp/tds.py). No statutory profile means new regime.
Professional tax follows the state slabs for the employee's work state, on
EARNED pay; a blank work state means no professional tax and no warning.
Net pay is floored at zero, with a warning when that happens.

Salary revision used: the latest one effective on or before the period end, so
re-running an old month does not pick up a later raise. If every revision is
dated after the period, the earliest one is used and a warning is attached.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
import calendar

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    Attendance,
    EmployeeExitRequest,
    EmployeeStatutoryProfile,
    Holiday,
    LeaveRequest,
    OptionalHolidayRequest,
    PayrollRecord,
    ProfessionalTaxSlab,
    Salary,
    WorkSchedule,
)
from .professional_tax import professional_tax as compute_professional_tax, state_key
from .tds import (
    TaxRulesMissing,
    compute_tds,
    fy_start_year,
    load_tax_rules,
    months_left_in_fy,
)
from .statutory import StatutoryRuleMissing, get_rule

ZERO = Decimal("0")
HALF = Decimal("0.5")
ONE = Decimal("1")
CENT = Decimal("0.01")

# Day statuses (also used by the Phase 3 calendar view)
NOT_EMPLOYED = "NOT_EMPLOYED"
WEEKLY_OFF = "WEEKLY_OFF"
HOLIDAY = "HOLIDAY"
PRESENT = "PRESENT"
HALF_DAY = "HALF_DAY"
PAID_LEAVE = "PAID_LEAVE"
UNPAID_LEAVE = "UNPAID_LEAVE"
HALF_PAID_LEAVE = "HALF_PAID_LEAVE"
HALF_UNPAID_LEAVE = "HALF_UNPAID_LEAVE"
ABSENT = "ABSENT"
PENDING = "PENDING"

DAY_LABELS = {
    "NOT_EMPLOYED": "Not employed",
    "WEEKLY_OFF": "Weekly off",
    "HOLIDAY": "Holiday",
    "PRESENT": "Present",
    "HALF_DAY": "Half day",
    "PAID_LEAVE": "Paid leave",
    "UNPAID_LEAVE": "Unpaid leave",
    "HALF_PAID_LEAVE": "Half paid leave",
    "HALF_UNPAID_LEAVE": "Half unpaid leave",
    "ABSENT": "Absent",
    "PENDING": "Upcoming",
}


def get_month_range(year, month):
    """First and last date of a calendar month."""
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class DayResult:
    date: date
    status: str
    paid: Decimal  # 0..1 share of the day that is paid
    note: str = ""

    @property
    def weekday(self):
        return self.date.strftime("%a")

    @property
    def label(self):
        return DAY_LABELS.get(self.status, self.status)


@dataclass
class PayrollResult:
    employee: object
    year: int
    month: int
    period_start: date
    period_end: date
    salary: object = None

    # skipped = no payroll could be produced (see skip_reason)
    skipped: bool = False
    skip_reason: str = ""
    warnings: list = field(default_factory=list)
    provisional: bool = False

    days: list = field(default_factory=list)
    days_in_period: int = 0
    not_employed_days: int = 0
    working_days: int = 0
    weekly_off_days: int = 0
    holiday_days: int = 0
    pending_days: int = 0
    present_days: Decimal = ZERO
    paid_leave_days: Decimal = ZERO
    unpaid_leave_days: Decimal = ZERO
    absent_days: Decimal = ZERO
    lop_days: Decimal = ZERO
    payable_days: Decimal = ZERO

    basic_salary: Decimal = ZERO
    hra: Decimal = ZERO
    gross_monthly: Decimal = ZERO
    basic_earned: Decimal = ZERO
    hra_earned: Decimal = ZERO
    gross_earned: Decimal = ZERO
    pf: Decimal = ZERO
    esi: Decimal = ZERO
    other_deductions: Decimal = ZERO
    tds: Decimal = ZERO
    professional_tax: Decimal = ZERO
    total_deductions: Decimal = ZERO
    net_pay: Decimal = ZERO

    # Other salary components and statutory wages (Phase 3)
    da: Decimal = ZERO
    special_allowance: Decimal = ZERO
    other_allowances: Decimal = ZERO
    da_earned: Decimal = ZERO
    special_earned: Decimal = ZERO
    other_earned: Decimal = ZERO
    statutory_wages: Decimal = ZERO

    # Employer share and wage bases (not deducted from the employee)
    pf_wage_base: Decimal = ZERO
    esi_wage_base: Decimal = ZERO
    employer_eps: Decimal = ZERO
    employer_epf: Decimal = ZERO
    employer_edli: Decimal = ZERO
    employer_pf_admin: Decimal = ZERO
    employer_esi: Decimal = ZERO

    @property
    def period_label(self):
        return date(self.year, self.month, 1).strftime("%B %Y")

    def to_record_fields(self):
        """Field values for PayrollRecord (everything except employee/year/month)."""
        return {
            "salary": self.salary,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "days_in_period": self.days_in_period,
            "working_days": self.working_days,
            "present_days": self.present_days,
            "paid_leave_days": self.paid_leave_days,
            "holiday_days": self.holiday_days,
            "weekly_off_days": self.weekly_off_days,
            "unpaid_leave_days": self.unpaid_leave_days,
            "absent_days": self.absent_days,
            "lop_days": self.lop_days,
            "payable_days": self.payable_days,
            "basic_salary": self.basic_salary,
            "hra": self.hra,
            "gross_monthly": self.gross_monthly,
            "gross_earned": self.gross_earned,
            "pf": self.pf,
            "esi": self.esi,
            "other_deductions": self.other_deductions,
            "tds": self.tds,
            "professional_tax": self.professional_tax,
            "total_deductions": self.total_deductions,
            "net_pay": self.net_pay,
            "pf_wage_base": self.pf_wage_base,
            "da": self.da,
            "special_allowance": self.special_allowance,
            "other_allowances": self.other_allowances,
            "statutory_wages": self.statutory_wages,
            "esi_wage_base": self.esi_wage_base,
            "employer_eps": self.employer_eps,
            "employer_epf": self.employer_epf,
            "employer_edli": self.employer_edli,
            "employer_pf_admin": self.employer_pf_admin,
            "employer_esi": self.employer_esi,
        }


# ──────────────────────────────────────────────────────────────────────────
# Preloading (a fixed number of queries no matter how many employees)
# ──────────────────────────────────────────────────────────────────────────
class _MonthData:
    def __init__(self, employees, start, end):
        emp_ids = [e.pk for e in employees]
        org_ids = {e.organization_id for e in employees}

        # Attendance: (employee_id, date) -> status
        self.attendance = {
            (emp_id, d): status
            for emp_id, d, status in Attendance.objects.filter(
                employee_id__in=emp_ids, date__gte=start, date__lte=end
            ).values_list("employee_id", "date", "status")
        }

        # Approved leave, expanded to (employee_id, date) -> LeaveRequest
        self.leave = {}
        leaves = LeaveRequest.objects.filter(
            employee_id__in=emp_ids,
            status="APPROVED",
            start_date__lte=end,
            end_date__gte=start,
        ).select_related("leave_type")
        for lv in leaves:
            cur = max(lv.start_date, start)
            while cur <= min(lv.end_date, end):
                self.leave[(lv.employee_id, cur)] = lv
                cur += timedelta(days=1)

        # Mandatory holidays: (organization_id, date)
        self.holidays = set(
            Holiday.objects.filter(
                organization_id__in=org_ids,
                holiday_type="MANDATORY",
                is_active=True,
                date__gte=start,
                date__lte=end,
            ).values_list("organization_id", "date")
        )

        # Approved optional holidays: (employee_id, date)
        self.optional_holidays = set(
            OptionalHolidayRequest.objects.filter(
                employee_id__in=emp_ids,
                status="APPROVED",
                holiday__holiday_type="OPTIONAL",
                holiday__is_active=True,
                holiday__date__gte=start,
                holiday__date__lte=end,
            ).values_list("employee_id", "holiday__date")
        )

        # Work schedules: the employee's own, else the organization default
        schedule_ids = {e.work_schedule_id for e in employees if e.work_schedule_id}
        self.schedules = WorkSchedule.objects.in_bulk(schedule_ids)
        self.default_schedules = {}
        for ws in WorkSchedule.objects.filter(
            organization_id__in=org_ids, is_default=True, is_active=True
        ):
            self.default_schedules[ws.organization_id] = ws

        # Completed exits: employee_id -> final last working date (latest wins)
        self.exit_dates = {}
        for emp_id, last_day in (
            EmployeeExitRequest.objects.filter(
                employee_id__in=emp_ids,
                status="COMPLETED",
                final_last_working_date__isnull=False,
            )
            .order_by("created_at")
            .values_list("employee_id", "final_last_working_date")
        ):
            self.exit_dates[emp_id] = last_day

        # Salary revisions per employee, newest effective first
        self.salaries = defaultdict(list)
        for sal in Salary.objects.filter(employee_id__in=emp_ids).order_by(
            "employee_id", "-effective_date", "-created_at"
        ):
            self.salaries[sal.employee_id].append(sal)

        # Statutory profiles: employee_id -> profile (none = FIXED)
        self.profiles = {
            p.employee_id: p
            for p in EmployeeStatutoryProfile.objects.filter(employee_id__in=emp_ids)
        }
        self._rule_date = start
        self._rules = {}
        self._pt_slabs = None
        self._start = start
        self._emp_ids = emp_ids
        self._tax_state = None
        self._prior = None

    def rule(self, key):
        """Statutory rule value on the first day of the month (cached)."""
        if key not in self._rules:
            self._rules[key] = get_rule(key, self._rule_date)
        return self._rules[key]

    def pt_slabs_for(self, state):
        """
        Professional tax slabs in force on the first day of the month for one
        state. All states are loaded with one query, the first time any
        employee has a work state, so months without one cost no extra query.
        """
        if self._pt_slabs is None:
            self._pt_slabs = defaultdict(list)
            slabs = ProfessionalTaxSlab.objects.filter(
                effective_from__lte=self._rule_date
            ).filter(
                Q(effective_to__isnull=True) | Q(effective_to__gte=self._rule_date)
            )
            for slab in slabs:
                self._pt_slabs[state_key(slab.state)].append(slab)
        return self._pt_slabs.get(state_key(state), [])

    def tax_rules(self):
        """(rules, error) for income tax on the first day of the month (cached)."""
        if self._tax_state is None:
            try:
                self._tax_state = (load_tax_rules(self._rule_date), None)
            except TaxRulesMissing as exc:
                self._tax_state = (None, exc)
        return self._tax_state

    def prior_payroll(self, employee_id):
        """
        {(year, month): (gross_earned, tds)} of the saved payroll records of
        this financial year before this month. One query for all employees.
        """
        if self._prior is None:
            self._prior = defaultdict(dict)
            fy = fy_start_year(self._start.year, self._start.month)
            in_fy = Q(year=fy, month__gte=4) | Q(year=fy + 1, month__lte=3)
            rows = PayrollRecord.objects.filter(
                employee_id__in=self._emp_ids
            ).filter(in_fy).values_list(
                "employee_id", "year", "month", "gross_earned", "tds"
            )
            for emp_id, y, m, gross, tds in rows:
                if (y, m) < (self._start.year, self._start.month):
                    self._prior[emp_id][(y, m)] = (Decimal(gross), Decimal(tds))
        return self._prior.get(employee_id, {})

    def schedule_for(self, employee):
        if employee.work_schedule_id and employee.work_schedule_id in self.schedules:
            return self.schedules[employee.work_schedule_id]
        return self.default_schedules.get(employee.organization_id)

    def salary_for(self, employee, period_end):
        """(salary, warning_or_None) for the revision effective at period_end."""
        revisions = self.salaries.get(employee.pk, [])
        if not revisions:
            return None, None
        for sal in revisions:  # newest first
            if sal.effective_date <= period_end:
                return sal, None
        earliest = revisions[-1]
        return earliest, (
            f"No salary revision was effective by {period_end:%d %b %Y}; "
            f"using the one effective {earliest.effective_date:%d %b %Y}."
        )


# ──────────────────────────────────────────────────────────────────────────
# Calculation
# ──────────────────────────────────────────────────────────────────────────
def _calculate_one(employee, year, month, start, end, as_of, data):
    result = PayrollResult(
        employee=employee, year=year, month=month, period_start=start, period_end=end,
        days_in_period=(end - start).days + 1,
    )

    salary, salary_warning = data.salary_for(employee, end)
    if salary is None:
        result.skipped = True
        result.skip_reason = "No salary record. Add a salary for this employee first."
        return result
    if salary.wage_type == "DAILY":
        result.skipped = True
        result.skip_reason = "Daily-wage employee. Use the wage register instead."
        return result
    result.salary = salary
    if salary_warning:
        result.warnings.append(salary_warning)

    schedule = data.schedule_for(employee)
    if schedule is None:
        result.warnings.append(
            "No work schedule found for this employee or organization; every day "
            "was treated as a working day."
        )

    hired = employee.date_hired
    last_day = data.exit_dates.get(employee.pk)
    emp_id, org_id = employee.pk, employee.organization_id

    leave_without_request = 0
    cur = start
    while cur <= end:
        day = _classify_day(
            cur, emp_id, org_id, schedule, hired, last_day, as_of, data, result
        )
        if day.note == "attendance-leave-without-request":
            leave_without_request += 1
            day.note = "Marked on leave without an approved leave request"
        result.days.append(day)
        cur += timedelta(days=1)

    if leave_without_request:
        result.warnings.append(
            f"{leave_without_request} day(s) are marked 'On Leave' in attendance "
            "without an approved leave request; they were paid."
        )

    employed_days = result.days_in_period - result.not_employed_days
    result.lop_days = result.unpaid_leave_days + result.absent_days
    result.payable_days = Decimal(employed_days) - result.lop_days
    result.provisional = result.pending_days > 0
    if result.provisional:
        result.warnings.append(
            f"{result.pending_days} day(s) have not happened yet and are assumed "
            "payable. Final figures are available after the period ends."
        )

    # ── Money ──────────────────────────────────────────────────────────
    ratio = result.payable_days / Decimal(result.days_in_period)
    result.basic_salary = _money(salary.basic_salary)
    result.hra = _money(salary.hra)
    result.da = _money(salary.da)
    result.special_allowance = _money(salary.special_allowance)
    result.other_allowances = _money(salary.other_allowances)
    result.gross_monthly = (
        result.basic_salary + result.hra + result.da
        + result.special_allowance + result.other_allowances
    )
    result.gross_earned = _money(result.gross_monthly * ratio)
    parts = _split_earned(
        result.basic_salary, result.da, result.special_allowance,
        result.other_allowances, ratio, result.gross_earned,
    )
    result.basic_earned = parts["basic"]
    result.hra_earned = parts["hra"]
    result.da_earned = parts["da"]
    result.special_earned = parts["special"]
    result.other_earned = parts["other"]

    try:
        result.statutory_wages = _statutory_wages(salary, result, data)
        stat = _statutory_amounts(
            salary, data.profiles.get(employee.pk),
            result.gross_monthly, result.gross_earned, result.statutory_wages, data,
        )
    except StatutoryRuleMissing as exc:
        result.skipped = True
        result.skip_reason = f"Statutory rule missing: {exc}"
        return result
    result.warnings.extend(stat.pop("warnings"))
    for name, value in stat.items():
        setattr(result, name, value)
    result.other_deductions = _money(salary.other_deductions)
    result.tds = _income_tax(employee, data.profiles.get(employee.pk), result, data)
    result.professional_tax = _professional_tax(
        data.profiles.get(employee.pk), result, data
    )
    result.total_deductions = (
        result.pf + result.esi + result.other_deductions + result.tds
        + result.professional_tax
    )

    net = result.gross_earned - result.total_deductions
    if net < ZERO:
        result.warnings.append(
            "Deductions exceed earnings for this month; net pay was set to zero."
        )
        net = ZERO
    result.net_pay = net
    return result


def _income_tax(employee, profile, result, data):
    """
    TDS for one month, projected over the financial year (April to March).
    Earlier months come from saved payroll records; a month with no record
    is assumed to have paid the full monthly gross with no TDS deducted.
    TDS off (NA) = zero. Missing tax rules = zero with a warning.
    """
    mode = profile.tds_mode if profile else "AUTO"
    if mode == "NA":
        return ZERO
    rules, error = data.tax_rules()
    if error:
        result.warnings.append(
            f"Income tax rules are not set up for this period ({error}); "
            "TDS was taken as zero."
        )
        return ZERO
    regime = profile.tax_regime if profile else "NEW"
    declared = _money(profile.declared_deductions) if profile and regime == "OLD" else ZERO

    prior = data.prior_payroll(employee.pk)
    hired = employee.date_hired
    ytd_gross = ZERO
    ytd_tds = ZERO
    missing = 0
    y, m = fy_start_year(result.year, result.month), 4
    while (y, m) < (result.year, result.month):
        if hired and (y, m) < (hired.year, hired.month):
            pass
        elif (y, m) in prior:
            gross, tds = prior[(y, m)]
            ytd_gross += gross
            ytd_tds += tds
        else:
            ytd_gross += result.gross_monthly
            missing += 1
        m += 1
        if m == 13:
            y, m = y + 1, 1

    months_left = months_left_in_fy(result.month)
    projected = (
        ytd_gross + result.gross_earned + result.gross_monthly * (months_left - 1)
    )
    out = compute_tds(rules, regime, projected, declared, ytd_tds, months_left)
    result.warnings.extend(out.warnings)
    if missing and out.monthly > ZERO:
        result.warnings.append(
            f"{missing} earlier month(s) of this financial year have no payroll "
            "record; they were assumed to have paid full salary with no TDS deducted."
        )
    return out.monthly


def _professional_tax(profile, result, data):
    """
    Professional tax for one month, on EARNED pay.
    No work state on the profile = not applicable: zero and no warning.
    A work state with no slabs set up = zero with a warning.
    """
    state = (profile.work_state if profile else "").strip()
    if not state:
        return ZERO
    slabs = data.pt_slabs_for(state)
    if not slabs:
        result.warnings.append(
            f"No professional tax slabs are set up for {state}; "
            "professional tax was taken as zero."
        )
        return ZERO
    amount, warning = compute_professional_tax(
        slabs, profile.gender, result.gross_earned, result.month
    )
    if warning:
        result.warnings.append(warning)
    return amount


def _split_earned(basic, da, special, other, ratio, gross_earned):
    """
    Earned amount of each component. HRA takes the rounding remainder so the
    parts always add up to gross_earned exactly.
    """
    parts = {
        "basic": _money(basic * ratio),
        "da": _money(da * ratio),
        "special": _money(special * ratio),
        "other": _money(other * ratio),
    }
    parts["hra"] = gross_earned - sum(parts.values())
    return parts


def _statutory_wages(salary, result, data):
    """
    Earned wages counted for PF. Salaries on the new structure follow the 50%
    wages rule: Basic + DA, but never less than 50% of earned pay. Older
    salaries keep using the full earned gross (Phase 2 behaviour).
    """
    if not salary.use_statutory_wages:
        return result.gross_earned
    share = data.rule("WAGES_MIN_SHARE")
    wages = result.basic_earned + result.da_earned
    floor = _money(result.gross_earned * share)
    if wages < floor:
        result.warnings.append(
            f"Basic + DA (Rs {wages:,.2f}) is below {share * 100:.0f}% of earned pay, "
            f"so PF is calculated on Rs {floor:,.2f} (the wages rule)."
        )
        return floor
    return wages


def _statutory_amounts(salary, profile, gross_monthly, gross_earned, pf_wages, data):
    """
    PF and ESI for one month, plus the employer's share.

    Modes (from the employee's EmployeeStatutoryProfile; no profile = FIXED):
      AUTO  employee amount is calculated from the statutory rules on earned wages
      FIXED employee amount is the typed amount on Salary (as before)
      NA    employee and employer amounts are zero
    The employer share is always calculated from the rules, except when the
    employee's amount is FIXED at zero (that means "does not contribute") or NA.
    Rules are looked up on the first day of the month, same as the wage register.
    ESI applies only when the full monthly gross is within the ESIC ceiling.
    """
    pf_mode = profile.pf_mode if profile else "FIXED"
    esi_mode = profile.esi_mode if profile else "FIXED"
    on_full_wage = bool(profile and profile.pf_on_full_wage)
    rule = data.rule
    warnings = []
    out = {
        "pf": ZERO, "esi": ZERO, "pf_wage_base": ZERO, "esi_wage_base": ZERO,
        "employer_eps": ZERO, "employer_epf": ZERO, "employer_edli": ZERO,
        "employer_pf_admin": ZERO, "employer_esi": ZERO,
    }

    # ── PF ─────────────────────────────────────────────────────────────
    if pf_mode != "NA":
        base = pf_wages
        if not on_full_wage:
            base = min(pf_wages, rule("EPF_WAGE_CEILING"))
        calc_pf = _money(base * rule("EPF_EMPLOYEE_RATE"))
        if pf_mode == "AUTO":
            out["pf"] = calc_pf
        else:
            out["pf"] = _money(salary.pf)
            if abs(out["pf"] - calc_pf) > ONE:
                warnings.append(
                    f"PF is a fixed Rs {out['pf']:,.2f}, but Rs {calc_pf:,.2f} "
                    "would be calculated on earned wages."
                )
        if out["pf"] > ZERO:
            out["pf_wage_base"] = _money(base)
            out["employer_eps"] = _money(base * rule("EPF_EMPLOYER_EPS_RATE"))
            out["employer_epf"] = _money(base * rule("EPF_EMPLOYER_EPF_RATE"))
            out["employer_edli"] = _money(base * rule("EDLI_RATE"))
            out["employer_pf_admin"] = _money(base * rule("EPF_ADMIN_RATE"))

    # ── ESI ────────────────────────────────────────────────────────────
    if esi_mode != "NA":
        ceiling = rule("ESIC_WAGE_CEILING")
        eligible = gross_monthly <= ceiling
        base = gross_earned if eligible else ZERO
        calc_esi = _money(base * rule("ESIC_EMPLOYEE_RATE"))
        if esi_mode == "AUTO":
            out["esi"] = calc_esi
        else:
            out["esi"] = _money(salary.esi)
            if out["esi"] > ZERO and not eligible:
                warnings.append(
                    f"ESI is a fixed Rs {out['esi']:,.2f}, but the monthly gross "
                    f"Rs {gross_monthly:,.2f} is above the ESI ceiling of Rs {ceiling:,.2f}."
                )
            elif abs(out["esi"] - calc_esi) > ONE:
                warnings.append(
                    f"ESI is a fixed Rs {out['esi']:,.2f}, but Rs {calc_esi:,.2f} "
                    "would be calculated on earned wages."
                )
        if esi_mode == "AUTO" or out["esi"] > ZERO:
            out["esi_wage_base"] = _money(base)
            out["employer_esi"] = _money(base * rule("ESIC_EMPLOYER_RATE"))

    out["warnings"] = warnings
    return out


def _classify_day(cur, emp_id, org_id, schedule, hired, last_day, as_of, data, result):
    """Classify one date, update the result's counters, return its DayResult."""

    def done(status, paid, note=""):
        return DayResult(date=cur, status=status, paid=paid, note=note)

    # 1. Outside employment
    if (hired and cur < hired) or (last_day and cur > last_day):
        result.not_employed_days += 1
        return done(NOT_EMPLOYED, ZERO, "Not employed on this date")

    # 2. Weekly off
    if schedule is not None and not schedule.is_working_day(cur):
        result.weekly_off_days += 1
        return done(WEEKLY_OFF, ONE)

    # 3. Holidays
    if (org_id, cur) in data.holidays or (emp_id, cur) in data.optional_holidays:
        result.holiday_days += 1
        return done(HOLIDAY, ONE)

    # From here on it is a working day.
    result.working_days += 1
    att_status = data.attendance.get((emp_id, cur))
    leave = data.leave.get((emp_id, cur))

    # 4. Full-day approved leave
    if leave is not None and leave.duration_type == "FULL_DAY":
        if leave.leave_type.is_paid:
            result.paid_leave_days += ONE
            return done(PAID_LEAVE, ONE, leave.leave_type.name)
        result.unpaid_leave_days += ONE
        return done(UNPAID_LEAVE, ZERO, leave.leave_type.name)

    # 5. Half-day approved leave: this half is the leave, the other half
    #    follows the attendance rules below.
    if leave is not None:
        leave_paid = leave.leave_type.is_paid
        if leave_paid:
            result.paid_leave_days += HALF
        else:
            result.unpaid_leave_days += HALF
        other_half_worked = att_status in ("PRESENT", "LATE", "HALF_DAY")
        if other_half_worked:
            result.present_days += HALF
            other_paid = HALF
        elif att_status is None and cur > as_of:
            result.pending_days += 1
            other_paid = HALF
        else:
            result.absent_days += HALF
            other_paid = ZERO
        paid = other_paid + (HALF if leave_paid else ZERO)
        status = HALF_PAID_LEAVE if leave_paid else HALF_UNPAID_LEAVE
        return done(status, paid, f"Half-day {leave.leave_type.name}")

    # 6. Attendance record
    if att_status in ("PRESENT", "LATE"):
        result.present_days += ONE
        return done(PRESENT, ONE, "Late" if att_status == "LATE" else "")
    if att_status == "HALF_DAY":
        result.present_days += HALF
        result.absent_days += HALF
        return done(HALF_DAY, HALF)
    if att_status == "LEAVE":
        result.paid_leave_days += ONE
        return done(PAID_LEAVE, ONE, "attendance-leave-without-request")
    if att_status == "ABSENT":
        result.absent_days += ONE
        return done(ABSENT, ZERO)

    # 7. No record yet and the day is not over
    if cur > as_of:
        result.pending_days += 1
        return done(PENDING, ONE, "Not yet happened")

    # 8. No record and the day is over
    result.absent_days += ONE
    return done(ABSENT, ZERO, "No attendance record")


def calculate_payroll_for_employees(employees, year, month, as_of=None):
    """
    Payroll for many employees with a fixed number of queries.
    Returns a list of PayrollResult in the same order as `employees`.
    """
    employees = list(employees)
    if not employees:
        return []
    start, end = get_month_range(year, month)
    as_of = as_of or timezone.localdate()
    data = _MonthData(employees, start, end)
    return [
        _calculate_one(emp, year, month, start, end, as_of, data) for emp in employees
    ]


def calculate_employee_payroll(employee, year, month, as_of=None):
    """Payroll for a single employee (same code path as the bulk version)."""
    return calculate_payroll_for_employees([employee], year, month, as_of)[0]


# ──────────────────────────────────────────────────────────────────────────
# Persistence
# ──────────────────────────────────────────────────────────────────────────
def save_payroll_record(result):
    """
    Create or refresh the PayrollRecord for a result. Raises ValidationError if
    the existing record is locked, or ValueError if the result was skipped.
    The returned record is NOT locked; call record.lock(user) to freeze it.
    """
    if result.skipped:
        raise ValueError(f"Cannot save a skipped payroll result: {result.skip_reason}")

    with transaction.atomic():
        record = (
            PayrollRecord.objects.select_for_update()
            .filter(employee=result.employee, year=result.year, month=result.month)
            .first()
        )
        fields = result.to_record_fields()
        if record is None:
            return PayrollRecord.objects.create(
                employee=result.employee, year=result.year, month=result.month, **fields
            )
        if record.is_locked:
            raise ValidationError(
                f"Payroll for {result.employee} is already locked for {result.period_label}."
            )
        for name, value in fields.items():
            setattr(record, name, value)
        record.save()
        return record


def earned_split(record):
    """
    (basic_earned, hra_earned) for a saved record, using the same proration as
    the calculation. Used by the payslip so it matches the stored gross exactly.
    """
    parts = earned_components(record)
    return parts["basic"], parts["hra"]


def earned_components(record):
    """Earned amount of each salary component for a saved record."""
    ratio = record.payable_days / Decimal(record.days_in_period)
    return _split_earned(
        record.basic_salary, record.da, record.special_allowance,
        record.other_allowances, ratio, record.gross_earned,
    )
