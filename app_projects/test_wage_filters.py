from decimal import Decimal

from django.contrib.auth.models import Permission
from django.urls import reverse

from app_projects.models import Project
from app_projects.test_leave_filters import LeaveFilterBase
from appEmp.models import Salary


class WageFilterTests(LeaveFilterBase):
    YEAR, MONTH = 2026, 10

    def make_salary(self, emp):
        return Salary.objects.create(
            employee=emp,
            organization=emp.organization,
            basic_salary=Decimal("10000"),
            wage_type="DAILY",
            daily_rate=Decimal("500"),
            is_active=True,
        )

    def setUp(self):
        super().setUp()
        self.sal_a = self.make_salary(self.in_a)
        self.sal_b = self.make_salary(self.in_b)
        self.sal_x = self.make_salary(self.loose)
        self.url = reverse(
            "wageRegisterBulk", kwargs={"year": self.YEAR, "month": self.MONTH}
        )

    def found(self, **params):
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200)
        ids = {r["salary"].pk for r in response.context["rows"]}
        return response, ids

    def all_ids(self):
        return {self.sal_a.pk, self.sal_b.pk, self.sal_x.pk}

    def test_dropdown_shown_for_admin(self):
        response, _ = self.found()
        self.assertTrue(response.context["project_filter_show"])

    def test_no_filter_shows_all(self):
        _, ids = self.found()
        self.assertEqual(ids, self.all_ids())

    def test_filter_by_project(self):
        _, ids = self.found(project=str(self.pa.uuid))
        self.assertEqual(ids, {self.sal_a.pk})

    def test_filter_unassigned(self):
        _, ids = self.found(project="unassigned")
        self.assertEqual(ids, {self.sal_x.pk})

    def test_other_org_project_uuid_is_ignored(self):
        response, ids = self.found(project=str(self.pc.uuid))
        self.assertEqual(response.context["project_filter_selected"], "")
        self.assertEqual(ids, self.all_ids())

    def test_archived_project_still_filters(self):
        Project.objects.filter(pk=self.pb.pk).update(status=Project.STATUS_ARCHIVED)
        _, ids = self.found(project=str(self.pb.uuid))
        self.assertEqual(ids, {self.sal_b.pk})

    def test_member_with_salary_perm_gets_no_dropdown_and_param_ignored(self):
        user = self.person(self.org1, "zz_wmem@example.com", role="member")
        perm = Permission.objects.get(
            codename="manage_salary", content_type__app_label="appEmp"
        )
        user.user_permissions.add(perm)
        self.client.force_login(user)
        response, ids = self.found(project=str(self.pa.uuid))
        self.assertFalse(response.context["project_filter_show"])
        self.assertEqual(response.context["project_filter_selected"], "")
        self.assertEqual(ids, self.all_ids())

    def test_formset_size_matches_filtered_rows(self):
        response, _ = self.found(project=str(self.pa.uuid))
        self.assertEqual(response.context["formset"].total_form_count(), 1)
