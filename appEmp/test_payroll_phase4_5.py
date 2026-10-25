"""Payroll Phases 4a, 4c and 5a: professional tax, deduction cap, income tax (TDS)."""
from collections import namedtuple
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from appEmp.models import (
    EmployeeStatutoryProfile,
    IncomeTaxSlab,
    PayrollRecord,
    Salary,
    StatutoryRule,
)
from appEmp.payroll_service import save_payroll_record
from appEmp.professional_tax import professional_tax, state_key
from appEmp.tds import (
    TaxRules,
    annual_tax,
    compute_tds,
    fy_start_year,
    months_left_in_fy,
)
from appEmp.test_payroll_service import YEAR, PayrollBase

D = Decimal
Slab = namedtuple("Slab", "gender above up_to month amount")

MEN = [
    Slab("M", D("0"), D("7500"), None, D("0")),
    Slab("M", D("7500"), D("10000"), None, D("175")),
    Slab("M", D("10000"), None, None, D("200")),
    Slab("M", D("10000"), None, 2, D("300")),
]


def make_rules():
    new = [
        (D("0"), D("400000"), D("0")),
        (D("400000"), D("800000"), D("0.05")),
        (D("800000"), D("1200000"), D("0.10")),
        (D("1200000"), D("1600000"), D("0.15")),
        (D("1600000"), D("2000000"), D("0.20")),
        (D("2000000"), D("2400000"), D("0.25")),
        (D("2400000"), None, D("0.30")),
    ]
    old = [
        (D("0"), D("250000"), D("0")),
        (D("250000"), D("500000"), D("0.05")),
        (D("500000"), D("1000000"), D("0.20")),
        (D("1000000"), None, D("0.30")),
    ]
    params = {
        "TAX_STD_DEDUCTION_NEW": D("75000"),
        "TAX_STD_DEDUCTION_OLD": D("50000"),
        "TAX_REBATE_LIMIT_NEW": D("1200000"),
        "TAX_REBATE_MAX_NEW": D("60000"),
        "TAX_REBATE_LIMIT_OLD": D("500000"),
        "TAX_REBATE_MAX_OLD": D("12500"),
        "TAX_CESS_RATE": D("0.04"),
        "TAX_SURCHARGE_FROM": D("5000000"),
    }
    return TaxRules(slabs={"NEW": new, "OLD": old}, params=params)


# ── Professional tax: the pure function ─────────────────────────────────
class ProfessionalTaxFunctionTests(SimpleTestCase):
    def test_pay_at_the_top_of_a_slab_belongs_to_that_slab(self):
        self.assertEqual(professional_tax(MEN, "M", D("7500"), 1), (D("0.00"), ""))
        self.assertEqual(professional_tax(MEN, "M", D("10000"), 1), (D("175.00"), ""))

    def test_pay_just_above_a_slab_moves_to_the_next(self):
        self.assertEqual(professional_tax(MEN, "M", D("8000"), 1), (D("175.00"), ""))
        self.assertEqual(professional_tax(MEN, "M", D("10000.01"), 1), (D("200.00"), ""))

    def test_month_specific_slab_wins_in_its_month_only(self):
        self.assertEqual(professional_tax(MEN, "M", D("12000"), 2), (D("300.00"), ""))
        self.assertEqual(professional_tax(MEN, "M", D("12000"), 1), (D("200.00"), ""))

    def test_gender_is_case_insensitive(self):
        self.assertEqual(professional_tax(MEN, "m", D("8000"), 1), (D("175.00"), ""))

    def test_missing_gender_gives_zero_and_a_warning(self):
        amount, warning = professional_tax(MEN, "", D("12000"), 1)
        self.assertEqual(amount, D("0"))
        self.assertIn("gender", warning)

    def test_a_gender_with_no_slabs_gives_zero_and_a_warning(self):
        amount, warning = professional_tax(MEN, "F", D("12000"), 1)
        self.assertEqual(amount, D("0"))
        self.assertIn("No professional tax slab matches", warning)

    def test_zero_pay_means_no_tax_and_no_warning(self):
        self.assertEqual(professional_tax(MEN, "M", D("0"), 1), (D("0"), ""))

    def test_no_slabs_gives_zero_and_a_warning(self):
        amount, warning = professional_tax([], "M", D("12000"), 1)
        self.assertEqual(amount, D("0"))
        self.assertIn("No professional tax slabs", warning)

    def test_overlapping_slabs_use_the_higher_start_and_warn(self):
        slabs = [
            Slab("A", D("0"), None, None, D("100")),
            Slab("A", D("5000"), None, None, D("200")),
        ]
        amount, warning = professional_tax(slabs, "", D("6000"), 1)
        self.assertEqual(amount, D("200.00"))
        self.assertIn("overlap", warning)

    def test_state_key_ignores_case_spaces_and_punctuation(self):
        self.assertEqual(state_key("Tamil  Nadu"), "tamilnadu")
        self.assertEqual(state_key(" tamil-nadu "), "tamilnadu")
        self.assertEqual(state_key(""), "")
        self.assertEqual(state_key(None), "")


# ── Professional tax inside payroll ─────────────────────────────────────
class ProfessionalTaxPayrollTests(PayrollBase):
    def set_profile(self, employee, **fields):
        EmployeeStatutoryProfile.objects.update_or_create(
            employee=employee, defaults=fields
        )

    def pt_employee(self, state, gender="", **kwargs):
        p = self.employee(**kwargs)
        self.full_attendance(p)
        self.set_profile(p, work_state=state, gender=gender)
        return p

    def test_no_work_state_means_no_tax_and_no_warning(self):
        p = self.employee()
        self.full_attendance(p)
        self.set_profile(p, work_state="")
        r = self.calc(p)
        self.assertEqual(r.professional_tax, D("0"))
        self.assertFalse(any("rofessional" in w for w in r.warnings))

    def test_seeded_maharashtra_slab_for_a_man(self):
        r = self.calc(self.pt_employee("Maharashtra", "M"))
        self.assertEqual(r.professional_tax, D("200.00"))
        self.assertEqual(
            r.total_deductions,
            r.pf + r.esi + r.other_deductions + r.tds + r.professional_tax,
        )

    def test_state_name_is_matched_loosely(self):
        r = self.calc(self.pt_employee("  MAHARASHTRA ", "M"))
        self.assertEqual(r.professional_tax, D("200.00"))

    def test_maharashtra_slabs_differ_for_men_and_women(self):
        man = self.calc(self.pt_employee("Maharashtra", "M", basic="15000", hra="0"))
        woman = self.calc(self.pt_employee("Maharashtra", "F", basic="15000", hra="0"))
        self.assertEqual(man.professional_tax, D("200.00"))
        self.assertEqual(woman.professional_tax, D("0.00"))

    def test_gender_missing_where_slabs_differ_warns(self):
        r = self.calc(self.pt_employee("Maharashtra", ""))
        self.assertEqual(r.professional_tax, D("0"))
        self.assertTrue(any("gender" in w for w in r.warnings))

    def test_state_without_pt_is_zero_and_quiet(self):
        r = self.calc(self.pt_employee("Uttar Pradesh"))
        self.assertEqual(r.professional_tax, D("0.00"))
        self.assertFalse(any("rofessional" in w for w in r.warnings))

    def test_unknown_state_is_zero_with_a_warning(self):
        r = self.calc(self.pt_employee("Atlantis"))
        self.assertEqual(r.professional_tax, D("0"))
        self.assertTrue(any("No professional tax slabs are set up for Atlantis" in w for w in r.warnings))


# ── Deduction cap ───────────────────────────────────────────────────────
class DeductionCapTests(PayrollBase):
    def test_other_deductions_are_trimmed_to_the_cap(self):
        p = self.employee(other="40000")
        self.full_attendance(p)
        r = self.calc(p)
        # earned 60,000; cap 30,000; PF 1,800 stays, so 28,200 of other fits.
        self.assertEqual(r.other_deductions, D("28200.00"))
        self.assertEqual(r.deferred_deductions, D("11800.00"))
        self.assertEqual(r.total_deductions, D("30000.00"))
        self.assertEqual(r.net_pay, D("30000.00"))
        self.assertTrue(any("capped" in w for w in r.warnings))

    def test_deductions_within_the_cap_are_untouched(self):
        p = self.employee(other="100")
        self.full_attendance(p)
        r = self.calc(p)
        self.assertEqual(r.other_deductions, D("100.00"))
        self.assertEqual(r.deferred_deductions, D("0"))
        self.assertFalse(any("capped" in w for w in r.warnings))

    def test_statutory_deductions_are_never_trimmed(self):
        p = self.employee(pf="40000", other="5000")
        self.full_attendance(p)
        r = self.calc(p)
        self.assertEqual(r.pf, D("40000.00"))
        self.assertEqual(r.other_deductions, D("0"))
        self.assertEqual(r.deferred_deductions, D("5000.00"))
        self.assertEqual(r.total_deductions, D("40000.00"))
        self.assertTrue(any("alone" in w for w in r.warnings))

    def test_missing_cap_rule_applies_no_cap_and_warns(self):
        StatutoryRule.objects.filter(key="DEDUCTION_CAP_SHARE").delete()
        p = self.employee(other="40000")
        self.full_attendance(p)
        r = self.calc(p)
        self.assertEqual(r.other_deductions, D("40000.00"))
        self.assertEqual(r.deferred_deductions, D("0"))
        self.assertTrue(any("deduction cap rule" in w for w in r.warnings))

    def test_deferred_amount_is_saved_on_the_record(self):
        p = self.employee(other="40000")
        self.full_attendance(p)
        record = save_payroll_record(self.calc(p))
        fresh = PayrollRecord.objects.get(pk=record.pk)
        self.assertEqual(fresh.deferred_deductions, D("11800.00"))
        self.assertEqual(fresh.other_deductions, D("28200.00"))


# ── Income tax: the pure functions ──────────────────────────────────────
class TaxEngineTests(SimpleTestCase):
    def setUp(self):
        self.rules = make_rules()

    def test_new_regime_tax_up_to_the_rebate_limit_is_zero(self):
        self.assertEqual(annual_tax(self.rules, "NEW", D("1200000")), D("0.00"))
        self.assertEqual(annual_tax(self.rules, "NEW", D("400000")), D("0.00"))
        self.assertEqual(annual_tax(self.rules, "NEW", D("-5")), D("0.00"))

    def test_new_regime_marginal_relief_just_above_the_limit(self):
        # slab tax 61,500 but never more than the 10,000 above the limit; plus 4% cess.
        self.assertEqual(annual_tax(self.rules, "NEW", D("1210000")), D("10400.00"))

    def test_new_regime_full_slabs_and_cess(self):
        self.assertEqual(annual_tax(self.rules, "NEW", D("1300000")), D("78000.00"))
        self.assertEqual(annual_tax(self.rules, "NEW", D("1500000")), D("109200.00"))

    def test_old_regime_rebate_and_no_marginal_relief(self):
        self.assertEqual(annual_tax(self.rules, "OLD", D("500000")), D("0.00"))
        self.assertEqual(annual_tax(self.rules, "OLD", D("1000000")), D("117000.00"))

    def test_new_regime_uses_the_standard_deduction(self):
        out = compute_tds(self.rules, "NEW", D("1500000"), D("0"), D("0"), 12)
        self.assertEqual(out.taxable_income, D("1425000"))
        self.assertEqual(out.annual_tax, D("97500.00"))
        self.assertEqual(out.monthly, D("8125.00"))

    def test_tds_already_deducted_is_spread_over_the_months_left(self):
        out = compute_tds(self.rules, "NEW", D("1500000"), D("0"), D("40000"), 6)
        self.assertEqual(out.monthly, D("9583.33"))

    def test_tds_never_goes_negative(self):
        out = compute_tds(self.rules, "NEW", D("1500000"), D("0"), D("200000"), 6)
        self.assertEqual(out.monthly, D("0.00"))

    def test_months_left_is_at_least_one(self):
        out = compute_tds(self.rules, "NEW", D("1500000"), D("0"), D("0"), 0)
        self.assertEqual(out.monthly, D("97500.00"))

    def test_old_regime_takes_declared_deductions(self):
        out = compute_tds(self.rules, "OLD", D("1000000"), D("150000"), D("0"), 12)
        self.assertEqual(out.taxable_income, D("800000"))
        self.assertEqual(out.annual_tax, D("75400.00"))
        self.assertEqual(out.monthly, D("6283.33"))

    def test_unknown_regime_is_treated_as_new(self):
        a = compute_tds(self.rules, "XYZ", D("1500000"), D("0"), D("0"), 12)
        b = compute_tds(self.rules, "NEW", D("1500000"), D("0"), D("0"), 12)
        self.assertEqual(a.monthly, b.monthly)

    def test_income_inside_the_rebate_gives_zero_tds(self):
        out = compute_tds(self.rules, "NEW", D("1200000"), D("0"), D("0"), 12)
        self.assertEqual(out.monthly, D("0.00"))

    def test_very_high_income_warns_about_surcharge(self):
        out = compute_tds(self.rules, "NEW", D("6000000"), D("0"), D("0"), 12)
        self.assertTrue(any("surcharge" in w for w in out.warnings))

    def test_financial_year_helpers(self):
        self.assertEqual((months_left_in_fy(4), months_left_in_fy(9)), (12, 7))
        self.assertEqual((months_left_in_fy(1), months_left_in_fy(3)), (3, 1))
        self.assertEqual(fy_start_year(2026, 4), 2026)
        self.assertEqual(fy_start_year(2027, 3), 2026)


# ── Income tax inside payroll ───────────────────────────────────────────
class IncomeTaxPayrollTests(PayrollBase):
    def set_profile(self, employee, **fields):
        EmployeeStatutoryProfile.objects.update_or_create(
            employee=employee, defaults=fields
        )

    def full(self, **kwargs):
        p = self.employee(**kwargs)
        self.full_attendance(p)
        return p

    def test_a_salary_inside_the_rebate_has_no_tds(self):
        r = self.calc(self.full())
        self.assertEqual(r.tds, D("0.00"))

    def test_high_salary_is_projected_over_the_year(self):
        r = self.calc(self.full(basic="100000", hra="50000"))
        # Five earlier months assumed at full pay: projected 18,00,000, tax 1,50,800, 7 months left.
        self.assertEqual(r.tds, D("21542.86"))
        self.assertTrue(any("earlier month" in w for w in r.warnings))

    def test_earlier_payroll_records_replace_the_assumption(self):
        p = self.full(basic="100000", hra="50000")
        for month in range(4, 9):
            PayrollRecord.objects.create(
                employee=p, year=YEAR, month=month,
                period_start=date(YEAR, month, 1), period_end=date(YEAR, month, 28),
                days_in_period=30,
                gross_earned=D("150000"), tds=D("10000"),
            )
        r = self.calc(p)
        # 1,50,800 for the year, 50,000 already deducted, 7 months left.
        self.assertEqual(r.tds, D("14400.00"))
        self.assertFalse(any("earlier month" in w for w in r.warnings))

    def test_old_regime_uses_the_declared_deductions(self):
        p = self.full(basic="100000", hra="0")
        self.set_profile(p, tax_regime="OLD", declared_deductions=D("150000"))
        r = self.calc(p)
        # Projected 12,00,000, taxable 10,00,000, tax 1,17,000, 7 months left.
        self.assertEqual(r.tds, D("16714.29"))

    def test_tds_switched_off_gives_zero(self):
        p = self.full(basic="100000", hra="50000")
        self.set_profile(p, tds_mode="NA")
        self.assertEqual(self.calc(p).tds, D("0"))

    def test_missing_tax_rules_give_zero_with_a_warning(self):
        IncomeTaxSlab.objects.all().delete()
        r = self.calc(self.full(basic="100000", hra="50000"))
        self.assertEqual(r.tds, D("0"))
        self.assertTrue(any("Income tax rules" in w for w in r.warnings))

    def test_salary_screen_estimate_follows_the_same_engine(self):
        low = self.full()
        high = self.full(basic="100000", hra="50000")
        self.assertEqual(
            Salary.objects.get(employee=low).calculate_monthly_tds(), D("0.00")
        )
        self.assertEqual(
            Salary.objects.get(employee=high).calculate_monthly_tds(), D("12566.67")
        )
