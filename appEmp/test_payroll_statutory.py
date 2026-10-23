"""Payroll Phase 2: PF and ESI on earned wages, employer share, payslip block."""
from datetime import date
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext

from appEmp.models import EmployeeStatutoryProfile, StatutoryRule
from appEmp.payroll_service import (
    calculate_employee_payroll,
    calculate_payroll_for_employees,
    save_payroll_record,
)
from appEmp.payslip_pdf import build_payslip_pdf
from appEmp.test_payroll_service import AS_OF, MONTH, YEAR, PayrollBase

D = Decimal


class StatutoryBase(PayrollBase):
    def profile(self, employee, **fields):
        EmployeeStatutoryProfile.objects.update_or_create(
            employee=employee, defaults=fields
        )

    def auto_employee(self, skip=(), **kwargs):
        p = self.employee(**kwargs)
        self.full_attendance(p, skip=skip)
        self.profile(p, pf_mode="AUTO", esi_mode="AUTO")
        return p


class FixedModeTests(StatutoryBase):
    def test_employee_without_profile_keeps_typed_amounts(self):
        p = self.employee(pf="1800", esi="0")
        self.full_attendance(p)
        r = self.calc(p)
        self.assertEqual((r.pf, r.esi), (D("1800.00"), D("0.00")))
        self.assertEqual(r.warnings, [])

    def test_fixed_profile_keeps_typed_amounts(self):
        p = self.employee(pf="1500")
        self.full_attendance(p)
        self.profile(p, pf_mode="FIXED", esi_mode="FIXED")
        r = self.calc(p)
        self.assertEqual(r.pf, D("1500.00"))

    def test_fixed_pf_still_gets_employer_share(self):
        p = self.employee(pf="1800")
        self.full_attendance(p)
        r = self.calc(p)
        self.assertEqual(r.pf_wage_base, D("15000.00"))
        self.assertEqual(r.employer_eps, D("1249.50"))
        self.assertEqual(r.employer_epf, D("550.50"))
        self.assertEqual(r.employer_edli, D("75.00"))
        self.assertEqual(r.employer_pf_admin, D("75.00"))

    def test_fixed_zero_pf_means_no_employer_share(self):
        p = self.employee(pf="0")
        self.full_attendance(p)
        r = self.calc(p)
        self.assertEqual(r.pf, D("0.00"))
        self.assertEqual(
            (r.employer_eps, r.employer_epf, r.employer_edli, r.employer_pf_admin, r.pf_wage_base),
            (D("0"), D("0"), D("0"), D("0"), D("0")),
        )

    def test_fixed_pf_that_differs_from_calculated_warns(self):
        p = self.employee(pf="1000")
        self.full_attendance(p)
        r = self.calc(p)
        self.assertEqual(r.pf, D("1000.00"))
        self.assertTrue(any("PF is a fixed Rs 1,000.00" in w for w in r.warnings))

    def test_fixed_esi_above_ceiling_warns(self):
        p = self.employee(esi="450")
        self.full_attendance(p)
        r = self.calc(p)
        self.assertEqual(r.esi, D("450.00"))
        self.assertTrue(any("above the ESI ceiling" in w for w in r.warnings))

    def test_fixed_esi_below_ceiling_gets_employer_esi(self):
        p = self.employee(basic="12000", hra="6000", pf="1800", esi="135")
        self.full_attendance(p)
        r = self.calc(p)
        self.assertEqual(r.esi, D("135.00"))
        self.assertEqual(r.esi_wage_base, D("18000.00"))
        self.assertEqual(r.employer_esi, D("585.00"))
        self.assertEqual(r.warnings, [])


class AutoModeTests(StatutoryBase):
    def test_pf_is_capped_at_the_ceiling(self):
        p = self.auto_employee()
        r = self.calc(p)
        self.assertEqual(r.pf, D("1800.00"))
        self.assertEqual(r.pf_wage_base, D("15000.00"))

    def test_pf_below_ceiling_uses_earned_wages(self):
        p = self.auto_employee(basic="8000", hra="2000")
        r = self.calc(p)
        self.assertEqual(r.gross_earned, D("10000.00"))
        self.assertEqual(r.pf, D("1200.00"))
        self.assertEqual(r.pf_wage_base, D("10000.00"))

    def test_loss_of_pay_reduces_pf_and_esi(self):
        p = self.auto_employee(basic="12000", hra="6000", skip={9, 10, 11})
        r = self.calc(p)
        self.assertEqual(r.gross_earned, D("16200.00"))
        self.assertEqual(r.pf, D("1800.00"))
        self.assertEqual(r.esi, D("121.50"))
        self.assertEqual(r.esi_wage_base, D("16200.00"))

    def test_loss_of_pay_can_bring_pf_below_the_ceiling(self):
        p = self.auto_employee(basic="12000", hra="4000", skip={1, 2, 3, 4, 7, 8, 9, 10})
        r = self.calc(p)
        # 8 days lost: payable 22 of 30
        self.assertEqual(r.gross_earned, D("11733.33"))
        self.assertEqual(r.pf, D("1408.00"))

    def test_pf_on_full_wage_ignores_the_ceiling(self):
        p = self.auto_employee()
        self.profile(p, pf_mode="AUTO", pf_on_full_wage=True)
        r = self.calc(p)
        self.assertEqual(r.pf, D("7200.00"))
        self.assertEqual(r.pf_wage_base, D("60000.00"))

    def test_esi_is_zero_above_the_ceiling(self):
        p = self.auto_employee()
        r = self.calc(p)
        self.assertEqual((r.esi, r.esi_wage_base, r.employer_esi), (D("0"), D("0"), D("0")))

    def test_esi_uses_monthly_gross_for_eligibility(self):
        # Gross 25,000 is above the ceiling; heavy loss of pay must not make
        # the employee eligible.
        p = self.auto_employee(basic="15000", hra="10000", skip=set(range(1, 20)))
        r = self.calc(p)
        self.assertLess(r.gross_earned, D("21000"))
        self.assertEqual(r.esi, D("0.00"))

    def test_employer_esi_rate(self):
        p = self.auto_employee(basic="12000", hra="6000", pf="0")
        r = self.calc(p)
        self.assertEqual(r.esi, D("135.00"))
        self.assertEqual(r.employer_esi, D("585.00"))

    def test_auto_amounts_have_no_fixed_warnings(self):
        p = self.auto_employee()
        self.assertEqual(self.calc(p).warnings, [])

    def test_september_stays_on_the_old_ceiling(self):
        p = self.auto_employee()
        self.assertEqual(self.calc(p).pf_wage_base, D("15000.00"))

    def test_october_uses_the_new_ceiling(self):
        p = self.employee()
        self.profile(p, pf_mode="AUTO", esi_mode="AUTO")
        r = calculate_employee_payroll(p, 2026, 10, as_of=date(2026, 9, 30))
        self.assertEqual(r.pf_wage_base, D("25000.00"))
        self.assertEqual(r.pf, D("3000.00"))
        self.assertEqual(r.employer_eps, D("2082.50"))

    def test_net_pay_reflects_calculated_deductions(self):
        p = self.auto_employee(basic="8000", hra="2000", other="100")
        r = self.calc(p)
        self.assertEqual(r.total_deductions, r.pf + r.esi + r.other_deductions + r.tds)
        self.assertEqual(r.net_pay, r.gross_earned - r.total_deductions)


class NotApplicableTests(StatutoryBase):
    def test_na_zeroes_employee_and_employer(self):
        p = self.employee(pf="1800", esi="100")
        self.full_attendance(p)
        self.profile(p, pf_mode="NA", esi_mode="NA")
        r = self.calc(p)
        self.assertEqual((r.pf, r.esi), (D("0"), D("0")))
        self.assertEqual(
            (r.employer_eps, r.employer_epf, r.employer_edli, r.employer_pf_admin, r.employer_esi),
            (D("0"),) * 5,
        )
        self.assertEqual(r.warnings, [])

    def test_pf_na_and_esi_auto_are_independent(self):
        p = self.employee(basic="12000", hra="6000", pf="0")
        self.full_attendance(p)
        self.profile(p, pf_mode="NA", esi_mode="AUTO")
        r = self.calc(p)
        self.assertEqual(r.pf, D("0"))
        self.assertEqual(r.esi, D("135.00"))


class RuleLookupTests(StatutoryBase):
    def test_changed_rule_value_is_used(self):
        rule = StatutoryRule.objects.get(key="EPF_EMPLOYEE_RATE", effective_to__isnull=True)
        rule.value = D("0.1000")
        rule.save()
        p = self.auto_employee(basic="8000", hra="2000")
        self.assertEqual(self.calc(p).pf, D("1000.00"))

    def test_missing_rule_skips_the_employee_with_a_reason(self):
        StatutoryRule.objects.filter(key="EPF_EMPLOYEE_RATE").delete()
        p = self.employee()
        self.full_attendance(p)
        r = self.calc(p)
        self.assertTrue(r.skipped)
        self.assertIn("EPF_EMPLOYEE_RATE", r.skip_reason)

    def test_na_employee_does_not_need_rules(self):
        StatutoryRule.objects.all().delete()
        p = self.employee()
        self.full_attendance(p)
        self.profile(p, pf_mode="NA", esi_mode="NA")
        r = self.calc(p)
        self.assertFalse(r.skipped)
        self.assertEqual((r.pf, r.esi), (D("0"), D("0")))


class BulkTests(StatutoryBase):
    def test_bulk_matches_single_and_query_count_does_not_grow(self):
        people = [self.auto_employee() for _ in range(2)]
        with CaptureQueriesContext(connection) as small:
            calculate_payroll_for_employees(people, YEAR, MONTH, as_of=AS_OF)
        more = people + [self.auto_employee() for _ in range(4)]
        with CaptureQueriesContext(connection) as large:
            results = calculate_payroll_for_employees(more, YEAR, MONTH, as_of=AS_OF)
        self.assertEqual(len(small), len(large))
        single = self.calc(people[0])
        self.assertEqual((results[0].pf, results[0].employer_eps), (single.pf, single.employer_eps))


class RecordAndPayslipTests(StatutoryBase):
    def test_record_stores_employer_share(self):
        p = self.auto_employee()
        record = save_payroll_record(self.calc(p))
        record.refresh_from_db()
        self.assertEqual(record.pf, D("1800.00"))
        self.assertEqual(record.pf_wage_base, D("15000.00"))
        self.assertEqual(record.employer_eps, D("1249.50"))
        self.assertEqual(record.employer_epf, D("550.50"))
        self.assertEqual(record.employer_edli, D("75.00"))
        self.assertEqual(record.employer_pf_admin, D("75.00"))
        self.assertEqual(record.employer_contribution_total, D("1950.00"))

    def test_resave_refreshes_employer_share(self):
        p = self.auto_employee(basic="8000", hra="2000")
        save_payroll_record(self.calc(p))
        self.profile(p, pf_mode="NA", esi_mode="NA")
        record = save_payroll_record(self.calc(p))
        record.refresh_from_db()
        self.assertEqual(record.employer_contribution_total, D("0.00"))
        self.assertEqual(record.pf, D("0.00"))

    def test_payslip_shows_employer_block(self):
        p = self.auto_employee()
        record = save_payroll_record(self.calc(p))
        record.lock(None)
        record.refresh_from_db()
        pdf = build_payslip_pdf(record, compress=False).read()
        self.assertIn(b"Employer contributions", pdf)
        self.assertIn(b"1,249.50", pdf)
        self.assertIn(b"Total Employer Contribution", pdf)

    def test_payslip_hides_employer_block_when_nothing_to_show(self):
        p = self.employee()
        self.full_attendance(p)
        self.profile(p, pf_mode="NA", esi_mode="NA")
        record = save_payroll_record(self.calc(p))
        record.lock(None)
        record.refresh_from_db()
        pdf = build_payslip_pdf(record, compress=False).read()
        self.assertNotIn(b"Employer contributions", pdf)
