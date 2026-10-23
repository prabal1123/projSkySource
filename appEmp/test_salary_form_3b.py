"""Payroll Phase 3b: salary form components, CTC calculator, PF/ESI mode editor."""
from datetime import date
from decimal import Decimal

from django.urls import reverse

from appEmp.forms import SalaryForm
from appEmp.models import EmployeeStatutoryProfile, Salary
from appEmp.test_payroll_service import MONTH, YEAR
from appEmp.test_payroll_views import PayrollViewBase

D = Decimal


def salary_post(**overrides):
    data = {
        "wage_type": "MONTHLY",
        "basic_salary": "24000.00",
        "daily_rate": "",
        "hra": "9600.00",
        "da": "",
        "special_allowance": "",
        "other_allowances": "",
        "pf": "0",
        "esi": "0",
        "other_deductions": "0",
        "effective_date": "2026-10-01",
    }
    data.update(overrides)
    return data


class SalaryFormTests(PayrollViewBase):
    def test_new_fields_are_saved(self):
        form = SalaryForm(salary_post(
            da="3000", special_allowance="5000.50", other_allowances="1000",
            use_statutory_wages="on",
        ))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["da"], D("3000"))
        self.assertEqual(form.cleaned_data["special_allowance"], D("5000.50"))
        self.assertEqual(form.cleaned_data["other_allowances"], D("1000"))
        self.assertTrue(form.cleaned_data["use_statutory_wages"])

    def test_empty_boxes_mean_zero_and_checkbox_is_off(self):
        form = SalaryForm(salary_post())
        self.assertTrue(form.is_valid(), form.errors)
        for name in ("da", "special_allowance", "other_allowances"):
            self.assertEqual(form.cleaned_data[name], D("0"))
        self.assertFalse(form.cleaned_data["use_statutory_wages"])

    def test_older_post_without_the_new_fields_still_works(self):
        data = salary_post()
        for name in ("da", "special_allowance", "other_allowances"):
            del data[name]
        form = SalaryForm(data)
        self.assertTrue(form.is_valid(), form.errors)

    def test_negative_amounts_are_rejected(self):
        for name in ("da", "special_allowance", "other_allowances"):
            form = SalaryForm(salary_post(**{name: "-1"}))
            self.assertFalse(form.is_valid(), name)
            self.assertIn(name, form.errors)


class SalaryUpdateViewTests(PayrollViewBase):
    def save_url(self, p):
        return reverse("salaryUpdate", args=[p.uuid])

    def test_hr_saves_a_revision_with_the_new_components(self):
        p = self.employee()
        response = self.client.post(self.save_url(p), salary_post(
            da="3000", special_allowance="5000", other_allowances="1000",
            use_statutory_wages="on",
        ))
        self.assertEqual(response.status_code, 302)
        salary = p.salary_records.get(is_active=True)
        self.assertEqual(
            (salary.da, salary.special_allowance, salary.other_allowances),
            (D("3000"), D("5000"), D("1000")),
        )
        self.assertTrue(salary.use_statutory_wages)
        self.assertEqual(salary.gross_monthly, D("24000") + D("9600") + D("9000"))

    def test_user_without_permission_cannot_save(self):
        p = self.employee()
        before = Salary.objects.count()
        nobody = self.make(self.org1, "zz_nobody3b@example.com")
        self.client.force_login(nobody.user)
        self.client.post(self.save_url(p), salary_post(da="3000"))
        self.assertEqual(Salary.objects.count(), before)


class ProfilePageTests(PayrollViewBase):
    def setUp(self):
        super().setUp()
        boss = self.make(self.org1, "zz_boss_3b@example.com")
        boss.user.is_superuser = True
        boss.user.save()
        self.client.force_login(boss.user)

    def page(self, p):
        return self.client.get(reverse("editProfile", args=[p.uuid]))

    def test_hr_sees_calculator_new_fields_and_mode_editor(self):
        p = self.employee()
        response = self.page(p)
        self.assertEqual(response.status_code, 200)
        for text in ("CTC calculator", "Special Allowance", "Other Allowances",
                     "Calculate PF on statutory wages", "PF and ESI settings"):
            self.assertContains(response, text)
        self.assertContains(response, reverse("salaryCtcPreview", args=[p.uuid]))
        self.assertContains(response, reverse("statutoryProfileUpdate", args=[p.uuid]))

    def test_employee_without_a_profile_row_is_shown_as_fixed(self):
        p = self.employee()
        self.assertFalse(EmployeeStatutoryProfile.objects.filter(employee=p).exists())
        form = self.page(p).context["statutory_form"]
        self.assertEqual(form["pf_mode"].value(), "FIXED")
        self.assertEqual(form["esi_mode"].value(), "FIXED")

    def test_existing_profile_shows_its_modes(self):
        p = self.employee()
        EmployeeStatutoryProfile.objects.create(employee=p, pf_mode="NA", esi_mode="AUTO")
        form = self.page(p).context["statutory_form"]
        self.assertEqual(form["pf_mode"].value(), "NA")
        self.assertEqual(form["esi_mode"].value(), "AUTO")

    def test_salary_block_lists_components_only_when_there_is_an_amount(self):
        p = self.employee()
        Salary.objects.filter(employee=p).update(is_active=False)
        Salary.objects.create(
            employee=p, basic_salary=D("24000"), hra=D("9600"), da=D("3000"),
            special_allowance=D("0"), other_allowances=D("0"),
            effective_date=date(2026, 10, 1), is_active=True,
        )
        html = self.page(p).content.decode()
        self.assertIn('<span class="stat-label">DA</span>', html)
        self.assertNotIn('<span class="stat-label">Special Allowance</span>', html)
        self.assertNotIn('<span class="stat-label">Other Allowances</span>', html)


class StatutoryProfileUpdateTests(PayrollViewBase):
    def save_url(self, p):
        return reverse("statutoryProfileUpdate", args=[p.uuid])

    def test_creates_the_profile_row_with_the_chosen_modes(self):
        p = self.employee()
        response = self.client.post(self.save_url(p), {"pf_mode": "AUTO", "esi_mode": "NA"})
        self.assertEqual(response.status_code, 302)
        profile = EmployeeStatutoryProfile.objects.get(employee=p)
        self.assertEqual((profile.pf_mode, profile.esi_mode), ("AUTO", "NA"))
        self.assertFalse(profile.pf_on_full_wage)
        self.assertEqual(profile.organization_id, p.organization_id)

    def test_updates_an_existing_row_and_keeps_tax_settings(self):
        p = self.employee()
        EmployeeStatutoryProfile.objects.create(
            employee=p, pf_mode="FIXED", esi_mode="FIXED",
            tax_regime="OLD", work_state="Karnataka",
        )
        self.client.post(self.save_url(p), {
            "pf_mode": "AUTO", "esi_mode": "AUTO", "pf_on_full_wage": "on",
        })
        profile = EmployeeStatutoryProfile.objects.get(employee=p)
        self.assertEqual((profile.pf_mode, profile.esi_mode), ("AUTO", "AUTO"))
        self.assertTrue(profile.pf_on_full_wage)
        self.assertEqual((profile.tax_regime, profile.work_state), ("OLD", "Karnataka"))
        self.assertEqual(EmployeeStatutoryProfile.objects.filter(employee=p).count(), 1)

    def test_an_invalid_mode_changes_nothing(self):
        p = self.employee()
        EmployeeStatutoryProfile.objects.create(employee=p, pf_mode="FIXED", esi_mode="FIXED")
        self.client.post(self.save_url(p), {"pf_mode": "BOGUS", "esi_mode": "AUTO"})
        profile = EmployeeStatutoryProfile.objects.get(employee=p)
        self.assertEqual((profile.pf_mode, profile.esi_mode), ("FIXED", "FIXED"))

    def test_user_without_permission_cannot_change_modes(self):
        p = self.employee()
        nobody = self.make(self.org1, "zz_nobody3b2@example.com")
        self.client.force_login(nobody.user)
        self.client.post(self.save_url(p), {"pf_mode": "AUTO", "esi_mode": "AUTO"})
        self.assertFalse(EmployeeStatutoryProfile.objects.filter(employee=p).exists())

    def test_employee_of_another_organization_is_not_found(self):
        stranger = self.make(self.org2, "zz_stranger3b@example.com")
        response = self.client.post(self.save_url(stranger), {"pf_mode": "AUTO", "esi_mode": "AUTO"})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(EmployeeStatutoryProfile.objects.filter(employee=stranger).exists())

    def test_mode_set_here_drives_the_payroll_calculation(self):
        p = self.full_employee(basic="40000", hra="20000", pf="1800")
        self.client.post(self.save_url(p), {"pf_mode": "NA", "esi_mode": "NA"})
        from appEmp.payroll_service import calculate_employee_payroll
        result = calculate_employee_payroll(p, YEAR, MONTH, as_of=date(2026, 10, 15))
        self.assertEqual(result.pf, D("0"))


class CtcPreviewTests(PayrollViewBase):
    def preview(self, p, **params):
        query = {"ctc": "50000", "basic_pct": "50", "hra_pct": "40", "on_date": "2026-09-01"}
        query.update(params)
        return self.client.get(reverse("salaryCtcPreview", args=[p.uuid]), query)

    def test_september_split_matches_the_agreed_numbers(self):
        p = self.employee()
        data = self.preview(p).json()
        self.assertEqual(data["gross"], "48050.00")
        self.assertEqual(data["employer_pf"], "1950.00")
        self.assertEqual(D(data["ctc_check"]), D("50000.00"))

    def test_october_split_uses_the_new_ceiling(self):
        p = self.employee()
        data = self.preview(p, on_date="2026-10-01").json()
        self.assertEqual(data["gross"], "46948.36")
        self.assertEqual(data["employer_pf"], "3051.64")

    def test_components_add_up_to_the_gross(self):
        p = self.employee()
        data = self.preview(p, on_date="2026-10-01", da="2000", other_allowances="500").json()
        parts = sum(D(data[k]) for k in (
            "basic", "hra", "da", "special_allowance", "other_allowances"))
        self.assertEqual(parts, D(data["gross"]))
        self.assertEqual(data["da"], "2000.00")
        self.assertEqual(data["other_allowances"], "500.00")

    def test_employee_with_pf_not_applicable_has_no_employer_pf(self):
        p = self.employee()
        EmployeeStatutoryProfile.objects.create(employee=p, pf_mode="NA", esi_mode="NA")
        data = self.preview(p, on_date="2026-10-01").json()
        self.assertEqual(data["employer_pf"], "0")
        self.assertEqual(data["gross"], "50000.00")

    def test_preview_saves_nothing(self):
        p = self.employee()
        before = Salary.objects.count()
        self.preview(p)
        self.assertEqual(Salary.objects.count(), before)

    def test_bad_input_is_a_clear_400(self):
        p = self.employee()
        for params in ({"ctc": ""}, {"ctc": "abc"}, {"ctc": "0"}, {"basic_pct": "0"},
                       {"basic_pct": "150"}, {"da": "-5"}, {"hra_pct": "x"},
                       {"ctc": "NaN"}):
            response = self.preview(p, **params)
            self.assertEqual(response.status_code, 400, params)
            self.assertTrue(response.json()["error"], params)

    def test_allowances_larger_than_the_gross_are_a_400(self):
        p = self.employee()
        response = self.preview(p, da="60000")
        self.assertEqual(response.status_code, 400)

    def test_user_without_permission_gets_403(self):
        p = self.employee()
        nobody = self.make(self.org1, "zz_nobody3b3@example.com")
        self.client.force_login(nobody.user)
        self.assertEqual(self.preview(p).status_code, 403)

    def test_employee_of_another_organization_is_not_found(self):
        stranger = self.make(self.org2, "zz_stranger3b2@example.com")
        self.assertEqual(self.preview(stranger).status_code, 404)
