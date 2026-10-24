"""Payroll Phase 2: the monthly payroll calculation service."""
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from appEmp import test_phase2_encryption as common
from appEmp.models import (
    Attendance,
    EmployeeExitRequest,
    Holiday,
    LeaveRequest,
    LeaveTypeMaster,
    OptionalHolidayRequest,
    PayrollRecord,
    Salary,
    WorkSchedule,
    empProfile,
)
from appEmp.payroll_service import (
    ABSENT,
    HOLIDAY,
    PENDING,
    WEEKLY_OFF,
    calculate_employee_payroll,
    calculate_payroll_for_employees,
    earned_split,
    save_payroll_record,
)

D = Decimal
# September 2026: 30 days. Sept 1 is a Tuesday, so Sat/Sun are
# 5,6,12,13,19,20,26,27 (8 weekly offs) and there are 22 Mon-Fri working days.
YEAR, MONTH = 2026, 9
AS_OF = date(2026, 10, 15)  # the month is over


def weekdays_of_month():
    return [
        date(YEAR, MONTH, d)
        for d in range(1, 31)
        if date(YEAR, MONTH, d).weekday() < 5
    ]


class PayrollBase(common.Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.mon_fri = WorkSchedule.objects.create(
            organization=cls.org1, name="ZZ Mon-Fri", is_default=False
        )
        cls.paid = LeaveTypeMaster.objects.create(
            organization=cls.org1, name="Casual", code="ZZCL", is_paid=True
        )
        cls.unpaid = LeaveTypeMaster.objects.create(
            organization=cls.org1, name="Loss of Pay", code="ZZLOP", is_paid=False
        )
        cls._counter = 0

    # ── builders ──────────────────────────────────────────────────────
    def employee(self, basic="40000", hra="20000", pf="1800", esi="0", other="0",
                 schedule="default", **fields):
        type(self)._counter += 1
        profile = self.make(self.org1, f"zz_pay{type(self)._counter}@example.com")
        profile.work_schedule = self.mon_fri if schedule == "default" else schedule
        for k, v in fields.items():
            setattr(profile, k, v)
        profile.save()
        if basic is not None:
            Salary.objects.create(
                employee=profile, basic_salary=D(basic), hra=D(hra), pf=D(pf),
                esi=D(esi), other_deductions=D(other),
                effective_date=date(2026, 1, 1),
            )
        return empProfile.objects.get(pk=profile.pk)

    def attend(self, profile, days, status="PRESENT"):
        for d in days:
            Attendance.objects.create(employee=profile, date=d, status=status)

    def full_attendance(self, profile, skip=()):
        self.attend(profile, [d for d in weekdays_of_month() if d.day not in skip])

    def leave(self, profile, leave_type, start, end, status="APPROVED", duration="FULL_DAY"):
        return LeaveRequest.objects.create(
            employee=profile, leave_type=leave_type, start_date=start, end_date=end,
            status=status, duration_type=duration, reason="test",
        )

    def holiday(self, day, kind="MANDATORY", org=None, active=True, name=None):
        return Holiday.objects.create(
            organization=org or self.org1, name=name or f"ZZ Holiday {day}",
            date=day, holiday_type=kind, is_active=active,
        )

    def calc(self, profile, as_of=AS_OF):
        return calculate_employee_payroll(profile, YEAR, MONTH, as_of=as_of)


class DayClassificationTests(PayrollBase):
    def test_full_attendance_pays_the_full_month(self):
        p = self.employee()
        self.full_attendance(p)
        r = self.calc(p)
        self.assertFalse(r.skipped)
        self.assertEqual((r.days_in_period, r.weekly_off_days, r.working_days), (30, 8, 22))
        self.assertEqual((r.present_days, r.lop_days, r.payable_days), (D("22.0"), D("0"), D("30")))
        self.assertEqual(r.gross_earned, D("60000.00"))
        self.assertEqual(r.tds, D("0.00"))  # 7,20,000 a year is inside the 12 lakh rebate
        self.assertEqual(r.total_deductions, D("1800.00"))  # 1800 PF
        self.assertEqual(r.net_pay, D("58200.00"))
        self.assertFalse(r.provisional)
        self.assertEqual(r.warnings, [])

    def test_working_day_without_a_record_is_absent_and_loses_pay(self):
        p = self.employee()
        self.full_attendance(p, skip={9, 22})
        r = self.calc(p)
        self.assertEqual((r.absent_days, r.lop_days, r.payable_days), (D("2.0"), D("2.0"), D("28.0")))
        self.assertEqual(r.gross_earned, D("56000.00"))
        self.assertEqual(r.basic_earned, D("37333.33"))
        self.assertEqual(r.hra_earned, D("18666.67"))
        self.assertEqual(r.basic_earned + r.hra_earned, r.gross_earned)
        self.assertEqual([d.date.day for d in r.days if d.status == ABSENT], [9, 22])

    def test_explicit_absent_record_loses_pay(self):
        p = self.employee()
        self.full_attendance(p, skip={9})
        self.attend(p, [date(YEAR, MONTH, 9)], status="ABSENT")
        self.assertEqual(self.calc(p).lop_days, D("1.0"))

    def test_late_counts_as_present(self):
        p = self.employee()
        self.full_attendance(p, skip={9})
        self.attend(p, [date(YEAR, MONTH, 9)], status="LATE")
        r = self.calc(p)
        self.assertEqual((r.lop_days, r.payable_days), (D("0"), D("30")))

    def test_half_day_attendance_loses_half_a_day(self):
        p = self.employee()
        self.full_attendance(p, skip={8})
        self.attend(p, [date(YEAR, MONTH, 8)], status="HALF_DAY")
        r = self.calc(p)
        self.assertEqual((r.present_days, r.absent_days, r.lop_days), (D("21.5"), D("0.5"), D("0.5")))
        self.assertEqual(r.payable_days, D("29.5"))
        self.assertEqual(r.gross_earned, D("59000.00"))

    def test_weekly_off_follows_the_work_schedule(self):
        six_day = WorkSchedule.objects.create(
            organization=self.org1, name="ZZ Mon-Sat", saturday=True
        )
        p = self.employee(schedule=six_day)
        r = self.calc(p)
        self.assertEqual(r.weekly_off_days, 4)  # only the four Sundays
        saturdays = [d for d in r.days if d.date.weekday() == 5]
        self.assertTrue(all(d.status == ABSENT for d in saturdays))  # no attendance

    def test_organization_default_schedule_used_when_employee_has_none(self):
        WorkSchedule.objects.filter(organization=self.org1).update(is_default=False)
        WorkSchedule.objects.filter(pk=self.mon_fri.pk).update(is_default=True, is_active=True)
        p = self.employee(schedule=None)
        empProfile.objects.filter(pk=p.pk).update(work_schedule=None)
        r = self.calc(empProfile.objects.get(pk=p.pk))
        self.assertEqual(r.weekly_off_days, 8)

    def test_missing_work_schedule_treats_every_day_as_working_with_warning(self):
        WorkSchedule.objects.filter(organization=self.org1).update(is_default=False, is_active=False)
        p = self.employee(schedule=None)
        empProfile.objects.filter(pk=p.pk).update(work_schedule=None)
        r = self.calc(empProfile.objects.get(pk=p.pk))
        self.assertEqual((r.weekly_off_days, r.working_days), (0, 30))
        self.assertTrue(any("No work schedule" in w for w in r.warnings))


class HolidayTests(PayrollBase):
    def test_mandatory_holiday_is_paid_without_attendance(self):
        self.holiday(date(YEAR, MONTH, 10))
        p = self.employee()
        self.full_attendance(p, skip={10})
        r = self.calc(p)
        self.assertEqual((r.holiday_days, r.working_days, r.lop_days), (1, 21, D("0")))
        self.assertEqual([d.status for d in r.days if d.date.day == 10], [HOLIDAY])

    def test_inactive_and_other_organization_holidays_do_not_apply(self):
        self.holiday(date(YEAR, MONTH, 10), active=False)
        self.holiday(date(YEAR, MONTH, 11), org=self.org2)
        p = self.employee()
        self.full_attendance(p, skip={10, 11})
        r = self.calc(p)
        self.assertEqual((r.holiday_days, r.absent_days), (0, D("2.0")))

    def test_optional_holiday_counts_only_when_approved_for_that_employee(self):
        opt = self.holiday(date(YEAR, MONTH, 11), kind="OPTIONAL")
        taker, other = self.employee(), self.employee()
        OptionalHolidayRequest.objects.create(employee=taker, holiday=opt, reason="x", status="APPROVED")
        OptionalHolidayRequest.objects.create(employee=other, holiday=opt, reason="x", status="PENDING")
        for p in (taker, other):
            self.full_attendance(p, skip={11})
        self.assertEqual((self.calc(taker).holiday_days, self.calc(taker).lop_days), (1, D("0")))
        self.assertEqual((self.calc(other).holiday_days, self.calc(other).lop_days), (0, D("1.0")))


class LeaveTests(PayrollBase):
    def test_paid_leave_is_paid_and_unpaid_leave_loses_pay(self):
        p = self.employee()
        self.full_attendance(p, skip={14, 15, 16, 17})
        self.leave(p, self.paid, date(YEAR, MONTH, 14), date(YEAR, MONTH, 15))
        self.leave(p, self.unpaid, date(YEAR, MONTH, 16), date(YEAR, MONTH, 17))
        r = self.calc(p)
        self.assertEqual((r.paid_leave_days, r.unpaid_leave_days), (D("2.0"), D("2.0")))
        self.assertEqual((r.lop_days, r.payable_days), (D("2.0"), D("28.0")))

    def test_pending_rejected_and_cancelled_leave_is_ignored(self):
        p = self.employee()
        self.full_attendance(p, skip={14, 15, 16})
        self.leave(p, self.paid, date(YEAR, MONTH, 14), date(YEAR, MONTH, 14), status="PENDING")
        self.leave(p, self.paid, date(YEAR, MONTH, 15), date(YEAR, MONTH, 15), status="REJECTED")
        self.leave(p, self.paid, date(YEAR, MONTH, 16), date(YEAR, MONTH, 16), status="CANCELLED")
        r = self.calc(p)
        self.assertEqual((r.paid_leave_days, r.absent_days), (D("0"), D("3.0")))

    def test_leave_over_a_weekend_only_counts_working_days(self):
        p = self.employee()
        self.full_attendance(p, skip={4, 7})
        self.leave(p, self.unpaid, date(YEAR, MONTH, 4), date(YEAR, MONTH, 7))  # Fri-Mon
        r = self.calc(p)
        self.assertEqual((r.unpaid_leave_days, r.weekly_off_days, r.lop_days), (D("2.0"), 8, D("2.0")))
        self.assertEqual([d.status for d in r.days if d.date.day in (5, 6)], [WEEKLY_OFF] * 2)

    def test_leave_on_a_holiday_is_not_counted_as_leave(self):
        self.holiday(date(YEAR, MONTH, 10))
        p = self.employee()
        self.full_attendance(p, skip={9, 10})
        self.leave(p, self.unpaid, date(YEAR, MONTH, 9), date(YEAR, MONTH, 10))
        r = self.calc(p)
        self.assertEqual((r.unpaid_leave_days, r.holiday_days), (D("1.0"), 1))

    def test_half_day_unpaid_leave_with_half_day_worked(self):
        p = self.employee()
        self.full_attendance(p, skip={8})
        self.attend(p, [date(YEAR, MONTH, 8)], status="HALF_DAY")
        self.leave(p, self.unpaid, date(YEAR, MONTH, 8), date(YEAR, MONTH, 8), duration="FIRST_HALF")
        r = self.calc(p)
        self.assertEqual((r.present_days, r.unpaid_leave_days, r.lop_days), (D("21.5"), D("0.5"), D("0.5")))
        self.assertEqual(r.payable_days, D("29.5"))

    def test_half_day_paid_leave_with_half_day_worked_loses_nothing(self):
        p = self.employee()
        self.full_attendance(p, skip={8})
        self.attend(p, [date(YEAR, MONTH, 8)], status="HALF_DAY")
        self.leave(p, self.paid, date(YEAR, MONTH, 8), date(YEAR, MONTH, 8), duration="SECOND_HALF")
        r = self.calc(p)
        self.assertEqual((r.paid_leave_days, r.lop_days, r.payable_days), (D("0.5"), D("0"), D("30")))

    def test_half_day_paid_leave_without_attendance_loses_the_other_half(self):
        p = self.employee()
        self.full_attendance(p, skip={8})
        self.leave(p, self.paid, date(YEAR, MONTH, 8), date(YEAR, MONTH, 8), duration="FIRST_HALF")
        r = self.calc(p)
        self.assertEqual((r.paid_leave_days, r.absent_days, r.lop_days), (D("0.5"), D("0.5"), D("0.5")))

    def test_attendance_marked_leave_without_a_request_is_paid_with_warning(self):
        p = self.employee()
        self.full_attendance(p, skip={9})
        self.attend(p, [date(YEAR, MONTH, 9)], status="LEAVE")
        r = self.calc(p)
        self.assertEqual((r.paid_leave_days, r.lop_days), (D("1.0"), D("0")))
        self.assertTrue(any("without an approved leave request" in w for w in r.warnings))


class EmploymentPeriodTests(PayrollBase):
    def test_joiner_is_paid_only_from_the_joining_date(self):
        p = self.employee(date_hired=date(YEAR, MONTH, 16))
        self.attend(p, [d for d in weekdays_of_month() if d.day >= 16])
        r = self.calc(p)
        self.assertEqual(r.not_employed_days, 15)
        self.assertEqual((r.lop_days, r.payable_days), (D("0"), D("15")))
        self.assertEqual(r.gross_earned, D("30000.00"))
        # Weekly offs are only counted from the joining date: 19, 20, 26, 27
        self.assertEqual(r.weekly_off_days, 4)

    def test_completed_exit_stops_pay_after_the_last_working_day(self):
        p = self.employee()
        self.attend(p, [d for d in weekdays_of_month() if d.day <= 20])
        EmployeeExitRequest.objects.create(
            employee=p, exit_type="RESIGNATION", reason="x", status="COMPLETED",
            final_last_working_date=date(YEAR, MONTH, 20),
        )
        r = self.calc(p)
        self.assertEqual(r.not_employed_days, 10)
        self.assertEqual((r.lop_days, r.payable_days), (D("0"), D("20")))
        self.assertEqual(r.gross_earned, D("40000.00"))

    def test_exit_that_is_not_completed_does_not_change_pay(self):
        p = self.employee()
        self.full_attendance(p)
        EmployeeExitRequest.objects.create(
            employee=p, exit_type="RESIGNATION", reason="x", status="READY_FOR_FINALIZATION",
            final_last_working_date=date(YEAR, MONTH, 20),
        )
        self.assertEqual(self.calc(p).payable_days, D("30"))


class ProvisionalMonthTests(PayrollBase):
    def test_days_that_have_not_happened_are_assumed_payable_and_flagged(self):
        p = self.employee()
        self.attend(p, [d for d in weekdays_of_month() if d.day <= 10])
        r = self.calc(p, as_of=date(YEAR, MONTH, 10))
        self.assertTrue(r.provisional)
        self.assertEqual(r.pending_days, 14)
        self.assertEqual((r.lop_days, r.payable_days), (D("0"), D("30")))
        self.assertEqual(sum(1 for d in r.days if d.status == PENDING), 14)
        self.assertTrue(any("not happened yet" in w for w in r.warnings))

    def test_missing_record_before_as_of_is_still_absent(self):
        p = self.employee()
        self.attend(p, [d for d in weekdays_of_month() if d.day <= 10 and d.day != 8])
        r = self.calc(p, as_of=date(YEAR, MONTH, 10))
        self.assertEqual(r.absent_days, D("1.0"))

    def test_future_approved_unpaid_leave_already_reduces_pay(self):
        p = self.employee()
        self.attend(p, [d for d in weekdays_of_month() if d.day <= 10])
        self.leave(p, self.unpaid, date(YEAR, MONTH, 24), date(YEAR, MONTH, 25))
        r = self.calc(p, as_of=date(YEAR, MONTH, 10))
        self.assertEqual((r.unpaid_leave_days, r.lop_days), (D("2.0"), D("2.0")))


class SalarySelectionTests(PayrollBase):
    def test_employee_without_salary_is_skipped(self):
        p = self.employee(basic=None)
        r = self.calc(p)
        self.assertTrue(r.skipped)
        self.assertIn("No salary", r.skip_reason)

    def test_daily_wage_employee_is_skipped(self):
        p = self.employee(basic=None)
        Salary.objects.create(
            employee=p, basic_salary=D("0.01"), wage_type="DAILY", daily_rate=D("800"),
            effective_date=date(2026, 1, 1),
        )
        r = self.calc(p)
        self.assertTrue(r.skipped)
        self.assertIn("wage register", r.skip_reason)

    def test_revision_effective_for_the_month_is_used(self):
        p = self.employee(basic="40000")  # effective 2026-01-01
        raise_ = Salary.objects.create(
            employee=p, basic_salary=D("50000"), hra=D("20000"), pf=D("1800"),
            effective_date=date(2026, 9, 20),
        )
        self.full_attendance(p)
        self.assertEqual(self.calc(p).salary.pk, raise_.pk)
        self.assertEqual(self.calc(p).basic_salary, D("50000.00"))
        august = calculate_employee_payroll(p, 2026, 8, as_of=AS_OF)
        self.assertEqual(august.basic_salary, D("40000.00"))

    def test_only_later_revision_is_used_with_a_warning(self):
        p = self.employee(basic=None)
        Salary.objects.create(
            employee=p, basic_salary=D("40000"), hra=D("20000"), pf=D("1800"),
            effective_date=date(2026, 10, 1),
        )
        self.full_attendance(p)
        r = self.calc(p)
        self.assertFalse(r.skipped)
        self.assertEqual(r.basic_salary, D("40000.00"))
        self.assertTrue(any("No salary revision was effective" in w for w in r.warnings))

    def test_esi_and_other_deductions_flow_through(self):
        p = self.employee(esi="450", other="100")
        self.full_attendance(p)
        r = self.calc(p)
        self.assertEqual((r.esi, r.other_deductions), (D("450.00"), D("100.00")))
        self.assertEqual(r.total_deductions, D("2350.00"))  # 1800+450+100, TDS is 0
        self.assertEqual(r.net_pay, D("57650.00"))

    def test_net_pay_never_goes_below_zero(self):
        p = self.employee(pf="70000")
        self.full_attendance(p)
        r = self.calc(p)
        self.assertEqual(r.net_pay, D("0"))
        self.assertTrue(any("net pay was set to zero" in w for w in r.warnings))


class BulkTests(PayrollBase):
    def test_bulk_matches_single_and_uses_a_fixed_number_of_queries(self):
        people = [self.employee() for _ in range(4)]
        for i, p in enumerate(people):
            self.full_attendance(p, skip=set(range(1, i + 1)) & {1, 2, 3})
        self.holiday(date(YEAR, MONTH, 10))

        with CaptureQueriesContext(connection) as one:
            calculate_payroll_for_employees(people[:1], YEAR, MONTH, as_of=AS_OF)
        with CaptureQueriesContext(connection) as many:
            bulk = calculate_payroll_for_employees(people, YEAR, MONTH, as_of=AS_OF)
        self.assertEqual(len(one), len(many))

        for person, bulk_result in zip(people, bulk):
            single = self.calc(person)
            self.assertEqual(bulk_result.to_record_fields(), single.to_record_fields())
            self.assertEqual(bulk_result.employee.pk, person.pk)

    def test_empty_input(self):
        self.assertEqual(calculate_payroll_for_employees([], YEAR, MONTH), [])


class PersistenceTests(PayrollBase):
    def test_save_creates_then_refreshes_one_record(self):
        p = self.employee()
        self.full_attendance(p, skip={9})
        first = save_payroll_record(self.calc(p))
        self.assertEqual(first.organization_id, self.org1.pk)
        self.assertEqual(first.lop_days, D("1.0"))
        self.assertEqual(first.net_pay, self.calc(p).net_pay)
        self.assertFalse(first.is_locked)

        self.attend(p, [date(YEAR, MONTH, 9)])  # attendance corrected
        second = save_payroll_record(self.calc(p))
        self.assertEqual(second.pk, first.pk)
        self.assertEqual(PayrollRecord.objects.filter(employee=p).count(), 1)
        self.assertEqual(PayrollRecord.objects.get(pk=first.pk).lop_days, D("0"))

    def test_locked_record_is_not_overwritten(self):
        p = self.employee()
        self.full_attendance(p)
        record = save_payroll_record(self.calc(p))
        record.lock(self.su)
        Attendance.objects.filter(employee=p, date=date(YEAR, MONTH, 9)).delete()
        with self.assertRaises(ValidationError):
            save_payroll_record(self.calc(p))
        self.assertEqual(PayrollRecord.objects.get(pk=record.pk).lop_days, D("0"))

    def test_skipped_result_cannot_be_saved(self):
        with self.assertRaises(ValueError):
            save_payroll_record(self.calc(self.employee(basic=None)))

    def test_saved_record_links_the_salary_revision_and_splits_earnings_consistently(self):
        p = self.employee()
        self.full_attendance(p, skip={9, 22})
        result = self.calc(p)
        record = PayrollRecord.objects.get(pk=save_payroll_record(result).pk)
        self.assertEqual(record.salary_id, result.salary.pk)
        self.assertEqual(earned_split(record), (result.basic_earned, result.hra_earned))
