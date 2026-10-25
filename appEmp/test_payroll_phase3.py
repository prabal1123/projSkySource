"""Payroll Phases 3a and 3c: CTC solver, statutory wages (50% rule), payroll screen and summary PDF."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from appEmp.ctc import CtcStructureError, solve_ctc_structure
from appEmp.models import EmployeeStatutoryProfile, Salary
from appEmp.test_payroll_pdf import PdfBase, pdf_text
from appEmp.test_payroll_service import MONTH, YEAR, PayrollBase
from appEmp.test_payroll_views import PayrollViewBase

D = Decimal
ON = date(2026, 9, 1)


def set_salary(employee, **fields):
    salary = Salary.objects.get(employee=employee)
    for name, value in fields.items():
        setattr(salary, name, value)
    salary.save()
    return employee


# ── CTC solver ──────────────────────────────────────────────────────────
class CtcSolverTests(TestCase):
    def solve(self, ctc, basic=50, hra=40, **kwargs):
        return solve_ctc_structure(ctc, basic, hra, ON, **kwargs)

    def test_high_ctc_puts_pf_on_the_ceiling(self):
        r = self.solve(100000)
        self.assertEqual(r["gross"], D("98050.00"))
        self.assertEqual(r["basic"], D("49025.00"))
        self.assertEqual(r["hra"], D("19610.00"))
        self.assertEqual(r["special_allowance"], D("29415.00"))
        self.assertEqual(r["employer_pf"], D("1950.00"))
        self.assertEqual(r["employer_esi"], D("0"))
        self.assertEqual(r["ctc_check"], D("100000.00"))
        self.assertEqual(r["difference"], D("0.00"))
        self.assertEqual(r["warnings"], [])

    def test_parts_add_up_and_the_ctc_is_met(self):
        for ctc in (20000, 35000, 60000, 100000, 250000):
            r = self.solve(ctc)
            parts = (
                r["basic"] + r["hra"] + r["da"]
                + r["special_allowance"] + r["other_allowances"]
            )
            self.assertEqual(r["gross"], parts, ctc)
            self.assertEqual(
                r["ctc_check"], r["gross"] + r["employer_pf"] + r["employer_esi"], ctc
            )
            self.assertLess(abs(r["difference"]), D("0.10"), ctc)
            self.assertGreaterEqual(r["special_allowance"], D("0"), ctc)

    def test_a_low_ctc_includes_employer_esi(self):
        r = self.solve(20000)
        self.assertGreater(r["employer_esi"], D("0"))
        self.assertLess(r["gross"], D("20000"))

    def test_esi_off_means_no_employer_esi(self):
        r = self.solve(20000, esi_applicable=False)
        self.assertEqual(r["employer_esi"], D("0"))

    def test_pf_and_esi_off_leaves_gross_equal_to_ctc(self):
        r = self.solve(100000, pf_applicable=False, esi_applicable=False)
        self.assertEqual(r["gross"], D("100000.00"))
        self.assertEqual(r["basic"], D("50000.00"))
        self.assertEqual(r["hra"], D("20000.00"))
        self.assertEqual(r["special_allowance"], D("30000.00"))
        self.assertEqual(r["employer_pf"], D("0"))
        self.assertEqual(r["employer_esi"], D("0"))
        self.assertEqual(r["ctc_check"], D("100000.00"))

    def test_fixed_da_and_other_allowances_are_kept(self):
        r = self.solve(100000, da=2000, other_allowances=1000)
        self.assertEqual(r["gross"], D("98050.00"))
        self.assertEqual(r["da"], D("2000.00"))
        self.assertEqual(r["other_allowances"], D("1000.00"))
        self.assertEqual(r["special_allowance"], D("26415.00"))
        self.assertEqual(r["statutory_wages"], D("51025.00"))
        self.assertEqual(r["employer_pf"], D("1950.00"))

    def test_a_low_basic_percentage_triggers_the_wages_rule_warning(self):
        r = self.solve(100000, basic=30, hra=0)
        self.assertEqual(r["gross"], D("98050.00"))
        self.assertEqual(r["basic"], D("29415.00"))
        self.assertEqual(r["special_allowance"], D("68635.00"))
        self.assertEqual(r["statutory_wages"], D("49025.00"))
        self.assertEqual(len(r["warnings"]), 1)
        self.assertIn("wages rule", r["warnings"][0])

    def test_pf_on_full_wage_costs_more_than_the_ceiling(self):
        r = self.solve(100000, pf_on_full_wage=True)
        self.assertGreater(r["employer_pf"], D("1950.00"))
        self.assertLess(abs(r["difference"]), D("0.10"))

    def test_components_larger_than_gross_are_refused(self):
        with self.assertRaises(CtcStructureError) as ctx:
            self.solve(100000, basic=90, hra=50)
        self.assertIn("more than the gross", str(ctx.exception))

    def test_bad_inputs_are_refused(self):
        for ctc, basic, hra in ((0, 50, 40), (-5, 50, 40), (100000, 0, 40),
                                (100000, 101, 40), (100000, 50, -1)):
            with self.assertRaises(CtcStructureError, msg=(ctc, basic, hra)):
                solve_ctc_structure(ctc, basic, hra, ON)


# ── Statutory wages (50% rule) inside payroll ───────────────────────────
class StatutoryWagesPayrollTests(PayrollBase):
    def wages_employee(self, basic, hra, flag=True, skip=(), **salary):
        p = self.employee(basic=basic, hra=hra)
        self.full_attendance(p, skip=skip)
        set_salary(p, use_statutory_wages=flag, **salary)
        EmployeeStatutoryProfile.objects.update_or_create(
            employee=p, defaults={"pf_mode": "AUTO", "esi_mode": "NA"}
        )
        return p

    def test_older_salaries_use_the_full_earned_pay(self):
        r = self.calc(self.wages_employee("20000", "30000", flag=False))
        self.assertEqual(r.statutory_wages, r.gross_earned)
        self.assertFalse(any("wages rule" in w for w in r.warnings))

    def test_basic_below_half_of_pay_is_lifted_to_half(self):
        r = self.calc(self.wages_employee("20000", "30000"))
        self.assertEqual(r.gross_earned, D("50000.00"))
        self.assertEqual(r.statutory_wages, D("25000.00"))
        self.assertTrue(any("wages rule" in w for w in r.warnings))

    def test_basic_above_half_of_pay_is_used_as_it_is(self):
        r = self.calc(self.wages_employee("30000", "20000"))
        self.assertEqual(r.statutory_wages, D("30000.00"))
        self.assertFalse(any("wages rule" in w for w in r.warnings))

    def test_da_counts_as_wages(self):
        r = self.calc(self.wages_employee("20000", "22000", da=D("8000")))
        self.assertEqual(r.gross_earned, D("50000.00"))
        self.assertEqual(r.statutory_wages, D("28000.00"))
        self.assertFalse(any("wages rule" in w for w in r.warnings))

    def test_the_rule_follows_earned_pay_when_days_are_lost(self):
        r = self.calc(self.wages_employee("20000", "30000", skip={9, 22}))
        self.assertEqual(r.gross_earned, D("46666.67"))
        self.assertEqual(r.statutory_wages, D("23333.34"))

    def test_pf_on_full_wage_follows_the_statutory_wages(self):
        with_rule = self.wages_employee("20000", "30000")
        EmployeeStatutoryProfile.objects.filter(employee=with_rule).update(pf_on_full_wage=True)
        without_rule = self.wages_employee("20000", "30000", flag=False)
        EmployeeStatutoryProfile.objects.filter(employee=without_rule).update(pf_on_full_wage=True)
        self.assertEqual(self.calc(with_rule).pf, D("3000.00"))
        self.assertEqual(self.calc(without_rule).pf, D("6000.00"))


# ── Payroll employee screen (3c) ────────────────────────────────────────
class EmployeeScreenComponentTests(PayrollViewBase):
    def page_url(self, p):
        return reverse("payrollEmployee", args=[YEAR, MONTH, p.uuid])

    def test_components_with_amounts_are_listed(self):
        p = self.full_employee()
        set_salary(p, da=D("5000"), special_allowance=D("3000"), other_allowances=D("2000"))
        response = self.get(self.page_url(p))
        self.assertContains(response, "DA (earned)")
        self.assertContains(response, "Special Allowance (earned)")
        self.assertContains(response, "Other Allowances (earned)")

    def test_components_without_amounts_are_not_listed(self):
        p = self.full_employee()
        response = self.get(self.page_url(p))
        self.assertNotContains(response, "DA (earned)")
        self.assertNotContains(response, "Special Allowance (earned)")
        self.assertNotContains(response, "Other Allowances (earned)")

    def test_statutory_wages_note_appears_when_pf_uses_a_different_base(self):
        p = self.full_employee(basic="20000", hra="30000")
        set_salary(p, use_statutory_wages=True)
        response = self.get(self.page_url(p))
        self.assertContains(response, "statutory wages of")
        self.assertContains(response, "25,000.00")

    def test_no_statutory_wages_note_on_older_salaries(self):
        p = self.full_employee()
        response = self.get(self.page_url(p))
        self.assertNotContains(response, "statutory wages of")

    def test_locked_figures_do_not_follow_later_salary_edits(self):
        p = self.full_employee()
        set_salary(p, da=D("5000"))
        self.post("lock")
        set_salary(p, da=D("9000"))
        response = self.get(self.page_url(p))
        self.assertContains(response, "5,000.00")
        self.assertNotContains(response, "9,000.00")


# ── Month summary PDF (3c) ──────────────────────────────────────────────
class SummaryPdfComponentTests(PdfBase):
    def test_extra_columns_and_totals_appear_when_someone_has_components(self):
        alice = self.named("Alice")
        self.named("Bob")
        set_salary(alice, da=D("5000"), special_allowance=D("3000"))
        self.post("lock")
        text = pdf_text(self.client.get(self.summary_url()).content)
        self.assertIn("allowance", text)
        self.assertGreaterEqual(text.count("5,000.00"), 2)

    def test_no_extra_columns_without_components(self):
        self.named("Alice")
        self.named("Bob")
        self.post("lock")
        text = pdf_text(self.client.get(self.summary_url()).content)
        self.assertNotIn("allowance", text.lower())
