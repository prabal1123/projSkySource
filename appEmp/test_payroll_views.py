"""Payroll Phase 3: roster and employee screens, actions and access rules."""
from datetime import date
from unittest import mock

from django.contrib.auth.models import Permission
from django.contrib.messages import get_messages
from django.urls import reverse

from app_organizations.entitlements import grant_modules
from app_projects.models import Project
from appEmp.models import Attendance, EmployeeExitRequest, PayrollRecord, empProfile
from appEmp.test_payroll_service import (
    D,
    MONTH,
    YEAR,
    PayrollBase,
    weekdays_of_month,
)

AFTER_MONTH = date(2026, 10, 15)
DURING_MONTH = date(2026, 9, 20)


def today_is(day):
    """Pin 'today' for both the views and the calculation service."""
    return mock.patch("django.utils.timezone.localdate", return_value=day)


class PayrollViewBase(PayrollBase):
    def setUp(self):
        super().setUp()
        grant_modules(self.org1, ["payroll"])

        self.hr = self.make(self.org1, "zz_hr@example.com")
        self.hr.user.user_permissions.add(Permission.objects.get(codename="manage_salary"))
        self.client.force_login(self.hr.user)

        session = self.client.session
        session["switched_org_id"] = self.org1.pk
        session.save()

        self.url = reverse("payrollCycle", args=[YEAR, MONTH])

    def messages(self, response):
        return [str(m) for m in get_messages(response.wsgi_request)]

    def full_employee(self, **kwargs):
        p = self.employee(**kwargs)
        self.full_attendance(p)
        return p

    def post(self, action, url=None, **extra):
        if action == "unlock":
            extra.setdefault("reason", "Correcting attendance for the month")
        with today_is(AFTER_MONTH):
            return self.client.post(url or self.url, {"action": action, **extra}, follow=True)

    def get(self, url=None):
        with today_is(AFTER_MONTH):
            return self.client.get(url or self.url)

    def row_for(self, response, profile):
        return next(r for r in response.context["rows"] if r["employee"].pk == profile.pk)


class AccessTests(PayrollViewBase):
    def test_anonymous_is_sent_to_login(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url.lower())

    def test_user_without_permission_is_turned_away_everywhere(self):
        nobody = self.make(self.org1, "zz_nobody@example.com")
        self.client.force_login(nobody.user)
        emp = self.employee()
        for url in (
            reverse("payroll"),
            self.url,
            reverse("payrollEmployee", args=[YEAR, MONTH, emp.uuid]),
        ):
            self.assertRedirects(self.client.get(url), reverse("dashboard"), fetch_redirect_response=False)
        response = self.client.post(self.url, {"action": "lock"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PayrollRecord.objects.count(), 0)

    def test_superuser_is_allowed(self):
        boss = self.make(self.org1, "zz_boss@example.com")
        boss.user.is_superuser = True
        boss.user.save()
        self.client.force_login(boss.user)
        session = self.client.session
        session["switched_org_id"] = self.org1.pk
        session.save()
        self.assertEqual(self.get().status_code, 200)

    def test_invalid_months_are_404(self):
        for y, m in ((2026, 13), (2026, 0), (1999, 5), (2101, 1)):
            self.assertEqual(self.client.get(reverse("payrollCycle", args=[y, m])).status_code, 404)


class IndexTests(PayrollViewBase):
    def test_defaults_to_the_previous_month(self):
        with today_is(date(2026, 10, 15)):
            response = self.client.get(reverse("payroll"))
        self.assertRedirects(response, reverse("payrollCycle", args=[2026, 9]), fetch_redirect_response=False)

    def test_previous_month_wraps_over_the_year_boundary(self):
        with today_is(date(2027, 1, 5)):
            response = self.client.get(reverse("payroll"))
        self.assertRedirects(response, reverse("payrollCycle", args=[2026, 12]), fetch_redirect_response=False)

    def test_month_picker_value_and_project_are_carried_over(self):
        response = self.client.get(reverse("payroll"), {"month": "2026-03", "project": "unassigned"})
        self.assertEqual(response.url, reverse("payrollCycle", args=[2026, 3]) + "?project=unassigned")

    def test_garbage_month_falls_back_with_an_error(self):
        response = self.client.get(reverse("payroll"), {"month": "banana"}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any("valid month" in m for m in self.messages(response)))


class RosterTests(PayrollViewBase):
    def test_lists_only_this_organizations_employees_with_correct_figures(self):
        a = self.full_employee()
        other_org = self.make(self.org2, "zz_other_org@example.com")
        response = self.get()
        self.assertEqual(response.status_code, 200)
        pks = [r["employee"].pk for r in response.context["rows"]]
        self.assertIn(a.pk, pks)
        self.assertNotIn(other_org.pk, pks)
        row = self.row_for(response, a)
        self.assertEqual(row["state"], "new")
        self.assertEqual(row["figures"]["payable_days"], D("30"))
        self.assertEqual(row["figures"]["net_pay"], D("58200.00"))
        self.assertContains(response, "Payroll — September 2026")

    def test_totals_add_up_the_displayed_rows(self):
        a, b = self.full_employee(), self.full_employee(basic="30000", hra="10000")
        response = self.get()
        net = self.row_for(response, a)["figures"]["net_pay"] + self.row_for(response, b)["figures"]["net_pay"]
        self.assertEqual(response.context["totals"]["net"], net)

    def test_employee_without_salary_is_listed_as_skipped_with_a_reason(self):
        p = self.employee(basic=None)
        response = self.get()
        row = self.row_for(response, p)
        self.assertEqual(row["state"], "skipped")
        self.assertIsNone(row["figures"])
        self.assertContains(response, "No salary record")

    def test_leaver_is_included_but_other_inactive_employees_are_not(self):
        leaver = self.full_employee()
        EmployeeExitRequest.objects.create(
            employee=leaver, exit_type="RESIGNATION", reason="x", status="COMPLETED",
            final_last_working_date=date(YEAR, MONTH, 25),
        )
        empProfile.objects.filter(pk=leaver.pk).update(is_active=False)
        gone = self.full_employee()
        empProfile.objects.filter(pk=gone.pk).update(is_active=False)
        pks = [r["employee"].pk for r in self.get().context["rows"]]
        self.assertIn(leaver.pk, pks)
        self.assertNotIn(gone.pk, pks)

    def test_employee_who_joins_after_the_month_is_excluded(self):
        late = self.employee(date_hired=date(2026, 11, 3))
        self.assertNotIn(late.pk, [r["employee"].pk for r in self.get().context["rows"]])

    def test_current_month_is_marked_provisional_and_lock_is_unavailable(self):
        p = self.employee()
        self.attend(p, [d for d in weekdays_of_month() if d.day <= 18])
        with today_is(DURING_MONTH):
            response = self.client.get(self.url)
        self.assertFalse(response.context["month_over"])
        self.assertTrue(self.row_for(response, p)["result"].provisional)
        self.assertContains(response, "has not ended yet")


class ActionTests(PayrollViewBase):
    def test_calculate_saves_drafts_and_skips_those_without_salary(self):
        a, b = self.full_employee(), self.full_employee()
        nosal = self.employee(basic=None)
        response = self.post("calculate")
        self.assertEqual(PayrollRecord.objects.filter(is_locked=False).count(), 2)
        self.assertFalse(PayrollRecord.objects.filter(employee=nosal).exists())
        self.assertEqual(self.row_for(response, a)["state"], "draft")
        self.assertTrue(any("saved 2" in m and "2 skipped" in m for m in self.messages(response)))

    def test_lock_freezes_the_month_and_records_who_did_it(self):
        a = self.full_employee()
        response = self.post("lock")
        record = PayrollRecord.objects.get(employee=a)
        self.assertTrue(record.is_locked)
        self.assertEqual(record.locked_by_id, self.hr.user.pk)
        self.assertEqual(self.row_for(response, a)["state"], "locked")
        self.assertTrue(any("Locked payroll for 1" in m for m in self.messages(response)))

    def test_lock_is_refused_before_the_month_has_ended(self):
        self.full_employee()
        with today_is(DURING_MONTH):
            response = self.client.post(self.url, {"action": "lock"}, follow=True)
        self.assertEqual(PayrollRecord.objects.count(), 0)
        self.assertTrue(any("can't be locked until the month has ended" in m for m in self.messages(response)))

    def test_calculate_is_allowed_before_the_month_ends(self):
        self.full_employee()
        with today_is(DURING_MONTH):
            self.client.post(self.url, {"action": "calculate"}, follow=True)
        self.assertEqual(PayrollRecord.objects.filter(is_locked=False).count(), 1)

    def test_locked_rows_show_the_snapshot_and_flag_later_changes(self):
        a = self.full_employee()
        self.post("lock")
        locked_net = PayrollRecord.objects.get(employee=a).net_pay
        Attendance.objects.filter(employee=a, date=date(YEAR, MONTH, 9)).delete()

        response = self.get()
        row = self.row_for(response, a)
        self.assertEqual(row["state"], "locked")
        self.assertTrue(row["stale"])
        self.assertEqual(row["figures"]["net_pay"], locked_net)
        self.assertNotEqual(row["result"].net_pay, locked_net)
        self.assertContains(response, "Changed since lock")

    def test_calculate_and_second_lock_never_touch_a_locked_record(self):
        a = self.full_employee()
        self.post("lock")
        before = PayrollRecord.objects.get(employee=a)
        Attendance.objects.filter(employee=a, date=date(YEAR, MONTH, 9)).delete()
        calc = self.post("calculate")
        relock = self.post("lock")
        after = PayrollRecord.objects.get(employee=a)
        self.assertEqual((after.net_pay, after.locked_at), (before.net_pay, before.locked_at))
        self.assertTrue(any("already locked" in m for m in self.messages(calc)))
        self.assertTrue(any("already locked" in m for m in self.messages(relock)))

    def test_unlock_returns_the_row_to_live_figures_and_allows_recalculation(self):
        a = self.full_employee()
        self.post("lock")
        Attendance.objects.filter(employee=a, date=date(YEAR, MONTH, 9)).delete()
        response = self.post("unlock")
        row = self.row_for(response, a)
        self.assertEqual(row["state"], "draft")
        self.assertEqual(row["figures"]["net_pay"], row["result"].net_pay)
        self.post("calculate")
        self.assertEqual(PayrollRecord.objects.get(employee=a).lop_days, D("1.0"))

    def test_unlock_with_nothing_locked_is_harmless(self):
        self.full_employee()
        response = self.post("unlock")
        self.assertTrue(any("None of the employees" in m for m in self.messages(response)))

    def test_unknown_action_changes_nothing(self):
        self.full_employee()
        response = self.post("delete_everything")
        self.assertEqual(PayrollRecord.objects.count(), 0)
        self.assertTrue(any("Unknown action" in m for m in self.messages(response)))

    def test_actions_never_reach_another_organizations_employees(self):
        self.full_employee()
        foreign = self.make(self.org2, "zz_foreign@example.com")
        self.post("calculate")
        self.assertFalse(PayrollRecord.objects.filter(employee=foreign).exists())


class ProjectScopeTests(PayrollViewBase):
    def setUp(self):
        super().setUp()
        boss = self.make(self.org1, "zz_boss2@example.com")
        boss.user.is_superuser = True
        boss.user.save()
        self.client.force_login(boss.user)
        
        session = self.client.session
        session["switched_org_id"] = self.org1.pk
        session.save()
        
        grant_modules(self.org1, ["payroll", "projects"])
        self.project = Project.objects.create(organization=self.org1, name="ZZ Site A")

    def test_lock_only_affects_the_filtered_project(self):
        inside = self.full_employee(project=self.project)
        outside = self.full_employee()
        url = f"{self.url}?project={str(self.project.uuid)}"
        response = self.post("lock", url=url)
        self.assertTrue(PayrollRecord.objects.get(employee=inside).is_locked)
        self.assertFalse(PayrollRecord.objects.filter(employee=outside).exists())
        self.assertEqual([r["employee"].pk for r in response.context["rows"]], [inside.pk])


class EmployeePageTests(PayrollViewBase):
    def page(self, profile):
        return reverse("payrollEmployee", args=[YEAR, MONTH, profile.uuid])

    def test_shows_attendance_money_and_day_by_day(self):
        p = self.full_employee()
        response = self.get(self.page(p))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["money"]["net_pay"], D("58200.00"))
        self.assertEqual(len(response.context["result"].days), 30)
        self.assertContains(response, "Weekly off")
        self.assertContains(response, "Net pay")

    def test_skipped_employee_shows_the_reason_and_no_money(self):
        p = self.employee(basic=None)
        response = self.get(self.page(p))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["money"])
        self.assertContains(response, "No salary record")

    def test_locked_employee_shows_the_snapshot_amounts(self):
        p = self.full_employee()
        self.post("lock", url=self.page(p))
        locked = PayrollRecord.objects.get(employee=p)
        Attendance.objects.filter(employee=p, date=date(YEAR, MONTH, 9)).delete()
        response = self.get(self.page(p))
        self.assertEqual(response.context["money"]["net_pay"], locked.net_pay)
        self.assertEqual(response.context["money"]["gross_earned"], locked.gross_earned)
        self.assertContains(response, "Changed since lock")

    def test_actions_on_the_employee_page_affect_only_that_employee(self):
        a, b = self.full_employee(), self.full_employee()
        self.post("lock", url=self.page(a))
        self.assertTrue(PayrollRecord.objects.get(employee=a).is_locked)
        self.assertFalse(PayrollRecord.objects.filter(employee=b).exists())
        self.post("unlock", url=self.page(a))
        self.assertFalse(PayrollRecord.objects.get(employee=a).is_locked)

    def test_other_organization_and_never_employed_are_404(self):
        foreign = self.make(self.org2, "zz_foreign2@example.com")
        late = self.employee(date_hired=date(2026, 11, 3))
        self.assertEqual(self.get(self.page(foreign)).status_code, 404)
        self.assertEqual(self.get(self.page(late)).status_code, 404)
