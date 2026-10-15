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
PF, ESI and other deductions are the fixed monthly amounts on the Salary.
TDS is the monthly TDS on the full (un-prorated) gross.
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
from django.utils import timezone

from .models import (
    Attendance,
    EmployeeExitRequest,
    Holiday,
    LeaveRequest,
    OptionalHolidayRequest,
    PayrollRecord,
    Salary,
    WorkSchedule,
)

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
    total_deductions: Decimal = ZERO
    net_pay: Decimal = ZERO

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
            "total_deductions": self.total_deductions,
            "net_pay": self.net_pay,
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
    result.gross_monthly = result.basic_salary + result.hra
    result.basic_earned = _money(result.basic_salary * ratio)
    result.gross_earned = _money(result.gross_monthly * ratio)
    result.hra_earned = result.gross_earned - result.basic_earned

    result.pf = _money(salary.pf)
    result.esi = _money(salary.esi)
    result.other_deductions = _money(salary.other_deductions)
    result.tds = _money(salary.calculate_monthly_tds())
    result.total_deductions = result.pf + result.esi + result.other_deductions + result.tds

    net = result.gross_earned - result.total_deductions
    if net < ZERO:
        result.warnings.append(
            "Deductions exceed earnings for this month; net pay was set to zero."
        )
        net = ZERO
    result.net_pay = net
    return result


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
    ratio = record.payable_days / Decimal(record.days_in_period)
    basic_earned = _money(record.basic_salary * ratio)
    return basic_earned, record.gross_earned - basic_earned
