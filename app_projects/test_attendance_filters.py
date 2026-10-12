from datetime import date

from django.contrib.auth.models import User
from django.urls import reverse

from app_projects.models import Project
from app_projects.test_leave_filters import LeaveFilterBase
from appEmp.models import Attendance, AttendanceException, empProfile


class ExceptionFilterBase(LeaveFilterBase):
    def setUp(self):
        super().setUp()
        today = date.today()
        self.exc_a, self.exc_b, self.exc_x = [
            AttendanceException.objects.create(
                attendance=Attendance.objects.create(employee=emp, date=today),
                raised_by=User.objects.get(pk=emp.user_id),
                reason="test",
            )
            for emp in (self.in_a, self.in_b, self.loose)
        ]

    def exceptions(self, **params):
        response = self.client.get(reverse("pendingAttendanceExceptions"), params)
        self.assertEqual(response.status_code, 200)
        uuids = {e.uuid for e in response.context["exception_requests"]}
        return response, uuids

    def everyone(self):
        return {self.exc_a.uuid, self.exc_b.uuid, self.exc_x.uuid}


class ReviewerExceptionFilterTests(ExceptionFilterBase):
    def test_dropdown_shown(self):
        response, _ = self.exceptions()
        self.assertTrue(response.context["project_filter_show"])

    def test_no_filter_shows_everyone(self):
        _, uuids = self.exceptions()
        self.assertEqual(uuids, self.everyone())

    def test_filter_by_project(self):
        _, uuids = self.exceptions(project=str(self.pa.uuid))
        self.assertEqual(uuids, {self.exc_a.uuid})

    def test_filter_unassigned(self):
        _, uuids = self.exceptions(project="unassigned")
        self.assertEqual(uuids, {self.exc_x.uuid})

    def test_archived_project_still_filters(self):
        Project.objects.filter(pk=self.pb.pk).update(status=Project.STATUS_ARCHIVED)
        _, uuids = self.exceptions(project=str(self.pb.uuid))
        self.assertEqual(uuids, {self.exc_b.uuid})

    def test_other_org_project_uuid_is_ignored(self):
        response, uuids = self.exceptions(project=str(self.pc.uuid))
        self.assertEqual(response.context["project_filter_selected"], "")
        self.assertEqual(uuids, self.everyone())


class ExceptionManagerScopeTests(ExceptionFilterBase):
    def report_to(self, user):
        manager = empProfile.objects.get(user=user)
        empProfile.objects.filter(pk__in=[self.in_a.pk, self.in_b.pk]).update(
            manager=manager
        )

    def test_manager_role_filters_within_own_reports_only(self):
        user = self.person(self.org1, "zz_amgr@example.com", role="manager")
        self.report_to(user)
        self.client.force_login(user)

        response, uuids = self.exceptions()
        self.assertTrue(response.context["project_filter_show"])
        self.assertEqual(uuids, {self.exc_a.uuid, self.exc_b.uuid})

        _, uuids = self.exceptions(project=str(self.pa.uuid))
        self.assertEqual(uuids, {self.exc_a.uuid})

        _, uuids = self.exceptions(project="unassigned")
        self.assertEqual(uuids, set())

    def test_member_manager_gets_no_dropdown_and_url_is_ignored(self):
        user = self.person(self.org1, "zz_amem@example.com", role="member")
        self.report_to(user)
        self.client.force_login(user)

        response, uuids = self.exceptions(project=str(self.pa.uuid))
        self.assertFalse(response.context["project_filter_show"])
        self.assertEqual(response.context["project_filter_selected"], "")
        self.assertEqual(uuids, {self.exc_a.uuid, self.exc_b.uuid})
