from datetime import date

from django.contrib.auth.models import User
from django.urls import reverse

from app_projects.models import Project
from app_projects.test_views import ViewBase
from appEmp.models import LeaveBalance, LeaveRequest, LeaveTypeMaster, empProfile


class LeaveFilterBase(ViewBase):
    def setUp(self):
        reviewer = self.make(self.org1, "zz_lrev@example.com")
        User.objects.filter(pk=reviewer.user_id).update(
            is_superuser=True, is_staff=True
        )
        self.reviewer = User.objects.get(pk=reviewer.user_id)
        self.client.force_login(self.reviewer)
        session = self.client.session
        session["switched_org_id"] = self.org1.id
        session.save()

        leave_type = LeaveTypeMaster.objects.create(
            organization=self.org1, name="Casual", code="CL"
        )
        self.in_a = self.make(self.org1, "zz_la@example.com", project=self.pa)
        self.in_b = self.make(self.org1, "zz_lb@example.com", project=self.pb)
        self.loose = self.make(self.org1, "zz_lx@example.com")

        today = date.today()
        self.req_a, self.req_b, self.req_x = [
            LeaveRequest.objects.create(
                employee=emp,
                leave_type=leave_type,
                start_date=today,
                end_date=today,
                reason="test",
            )
            for emp in (self.in_a, self.in_b, self.loose)
        ]

    def found(self, url_name, **params):
        response = self.client.get(reverse(url_name), params)
        self.assertEqual(response.status_code, 200)
        uuids = {leave.uuid for leave in response.context["leave_requests"]}
        return response, uuids


class ReviewerFilterTests(LeaveFilterBase):
    SCREENS = ("pendingLeaveRequests", "allLeaveRequests")

    def test_dropdown_shown(self):
        for name in self.SCREENS:
            response, _ = self.found(name)
            self.assertTrue(response.context["project_filter_show"], name)

    def test_no_filter_shows_everyone(self):
        for name in self.SCREENS:
            _, uuids = self.found(name)
            self.assertEqual(
                uuids, {self.req_a.uuid, self.req_b.uuid, self.req_x.uuid}, name
            )

    def test_filter_by_project(self):
        for name in self.SCREENS:
            _, uuids = self.found(name, project=str(self.pa.uuid))
            self.assertEqual(uuids, {self.req_a.uuid}, name)

    def test_filter_unassigned(self):
        for name in self.SCREENS:
            _, uuids = self.found(name, project="unassigned")
            self.assertEqual(uuids, {self.req_x.uuid}, name)

    def test_archived_project_still_filters(self):
        Project.objects.filter(pk=self.pb.pk).update(status=Project.STATUS_ARCHIVED)
        for name in self.SCREENS:
            _, uuids = self.found(name, project=str(self.pb.uuid))
            self.assertEqual(uuids, {self.req_b.uuid}, name)

    def test_other_org_project_uuid_is_ignored(self):
        for name in self.SCREENS:
            response, uuids = self.found(name, project=str(self.pc.uuid))
            self.assertEqual(response.context["project_filter_selected"], "", name)
            self.assertEqual(
                uuids, {self.req_a.uuid, self.req_b.uuid, self.req_x.uuid}, name
            )

    def test_project_filter_combines_with_status_filter(self):
        LeaveRequest.objects.filter(pk=self.req_a.pk).update(status="APPROVED")
        _, uuids = self.found(
            "allLeaveRequests", project=str(self.pa.uuid), status="PENDING"
        )
        self.assertEqual(uuids, set())
        _, uuids = self.found(
            "allLeaveRequests", project=str(self.pa.uuid), status="APPROVED"
        )
        self.assertEqual(uuids, {self.req_a.uuid})


class PendingManagerScopeTests(LeaveFilterBase):
    def report_to(self, user):
        manager = empProfile.objects.get(user=user)
        empProfile.objects.filter(pk__in=[self.in_a.pk, self.in_b.pk]).update(
            manager=manager
        )

    def test_manager_role_filters_within_own_reports_only(self):
        user = self.person(self.org1, "zz_lmgr@example.com", role="manager")
        self.report_to(user)
        self.client.force_login(user)

        response, uuids = self.found("pendingLeaveRequests")
        self.assertTrue(response.context["project_filter_show"])
        self.assertEqual(uuids, {self.req_a.uuid, self.req_b.uuid})

        _, uuids = self.found("pendingLeaveRequests", project=str(self.pa.uuid))
        self.assertEqual(uuids, {self.req_a.uuid})

        _, uuids = self.found("pendingLeaveRequests", project="unassigned")
        self.assertEqual(uuids, set())

    def test_member_manager_gets_no_dropdown_and_url_is_ignored(self):
        user = self.person(self.org1, "zz_lmem@example.com", role="member")
        self.report_to(user)
        self.client.force_login(user)

        response, uuids = self.found(
            "pendingLeaveRequests", project=str(self.pa.uuid)
        )
        self.assertFalse(response.context["project_filter_show"])
        self.assertEqual(response.context["project_filter_selected"], "")
        self.assertEqual(uuids, {self.req_a.uuid, self.req_b.uuid})


class BalanceFilterTests(LeaveFilterBase):
    def setUp(self):
        super().setUp()
        leave_type = LeaveTypeMaster.objects.get(organization=self.org1, code="CL")
        self.bal_a, self.bal_b, self.bal_x = [
            LeaveBalance.objects.create(employee=emp, leave_type=leave_type)
            for emp in (self.in_a, self.in_b, self.loose)
        ]

    def balances(self, **params):
        response = self.client.get(reverse("leaveBalanceList"), params)
        self.assertEqual(response.status_code, 200)
        return response, {b.uuid for b in response.context["balances"]}

    def test_dropdown_shown(self):
        response, _ = self.balances()
        self.assertTrue(response.context["project_filter_show"])

    def test_no_filter_shows_everyone(self):
        _, uuids = self.balances()
        self.assertEqual(uuids, {self.bal_a.uuid, self.bal_b.uuid, self.bal_x.uuid})

    def test_filter_by_project(self):
        _, uuids = self.balances(project=str(self.pa.uuid))
        self.assertEqual(uuids, {self.bal_a.uuid})

    def test_filter_unassigned(self):
        _, uuids = self.balances(project="unassigned")
        self.assertEqual(uuids, {self.bal_x.uuid})

    def test_archived_project_still_filters(self):
        Project.objects.filter(pk=self.pb.pk).update(status=Project.STATUS_ARCHIVED)
        _, uuids = self.balances(project=str(self.pb.uuid))
        self.assertEqual(uuids, {self.bal_b.uuid})

    def test_other_org_project_uuid_is_ignored(self):
        response, uuids = self.balances(project=str(self.pc.uuid))
        self.assertEqual(response.context["project_filter_selected"], "")
        self.assertEqual(uuids, {self.bal_a.uuid, self.bal_b.uuid, self.bal_x.uuid})

    def test_project_filter_combines_with_employee_filter(self):
        _, uuids = self.balances(
            project=str(self.pa.uuid), employee=str(self.in_b.id)
        )
        self.assertEqual(uuids, set())
        _, uuids = self.balances(
            project=str(self.pa.uuid), employee=str(self.in_a.id)
        )
        self.assertEqual(uuids, {self.bal_a.uuid})
