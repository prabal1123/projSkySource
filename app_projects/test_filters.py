from django.test import RequestFactory
from django.urls import reverse

from app_projects.filters import (
    clean_project_filter,
    project_filter_context,
)
from app_projects.models import Project
from app_projects.test_views import ViewBase
from appEmp.views import _filtered_emp_queryset


class FilterBase(ViewBase):
    def setUp(self):
        self.client.force_login(self.su)
        session = self.client.session
        session["switched_org_id"] = self.org1.id
        session.save()
        self.in_a = self.make(self.org1, "zz_f1@example.com", project=self.pa)
        self.in_b = self.make(self.org1, "zz_f2@example.com", project=self.pb)
        self.loose = self.make(self.org1, "zz_f3@example.com")

    def listed(self, **params):
        response = self.client.get(reverse("employeeList"), params)
        self.assertEqual(response.status_code, 200)
        return response, {row["uuid"] for row in response.context["objects"]}


class EmployeeListFilterTests(FilterBase):
    def test_filter_by_project(self):
        _, found = self.listed(project=str(self.pa.uuid))
        self.assertIn(self.in_a.uuid, found)
        self.assertNotIn(self.in_b.uuid, found)
        self.assertNotIn(self.loose.uuid, found)

    def test_filter_unassigned(self):
        _, found = self.listed(project="unassigned")
        self.assertIn(self.loose.uuid, found)
        self.assertNotIn(self.in_a.uuid, found)
        self.assertNotIn(self.in_b.uuid, found)

    def test_archived_project_can_be_filtered_and_is_labelled(self):
        Project.objects.filter(pk=self.pb.pk).update(status=Project.STATUS_ARCHIVED)
        response, found = self.listed(project=str(self.pb.uuid))
        self.assertIn(self.in_b.uuid, found)
        self.assertNotIn(self.in_a.uuid, found)
        labels = {
            o["uuid"]: o["label"] for o in response.context["project_filter_options"]
        }
        self.assertTrue(labels[str(self.pb.uuid)].endswith(" (archived)"))

    def test_other_org_project_uuid_is_ignored(self):
        response, found = self.listed(project=str(self.pc.uuid))
        self.assertEqual(response.context["project_filter_selected"], "")
        self.assertIn(self.in_a.uuid, found)
        self.assertIn(self.in_b.uuid, found)
        self.assertIn(self.loose.uuid, found)

    def test_garbage_value_is_ignored(self):
        response, found = self.listed(project="not-a-uuid")
        self.assertEqual(response.context["project_filter_selected"], "")
        self.assertIn(self.in_a.uuid, found)
        self.assertIn(self.loose.uuid, found)

    def test_pdf_accepts_the_same_filter(self):
        response = self.client.get(
            reverse("employeeListPdf"), {"project": str(self.pa.uuid)}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")


class FilterVisibilityTests(FilterBase):
    def request_for(self, user, **params):
        request = RequestFactory().get("/", params)
        request.user = user
        request.current_org = self.org1
        return request

    def test_dropdown_shown_to_superuser(self):
        context = project_filter_context(self.request_for(self.su))
        self.assertTrue(context["project_filter_show"])

    def test_manager_sees_dropdown_member_does_not(self):
        manager = self.person(self.org1, "zz_fmgr@example.com", role="manager")
        member = self.person(self.org1, "zz_fmem@example.com", role="member")
        self.assertTrue(project_filter_context(self.request_for(manager))["project_filter_show"])
        self.assertFalse(project_filter_context(self.request_for(member))["project_filter_show"])

    def test_member_cannot_filter_by_url(self):
        member = self.person(self.org1, "zz_fmem2@example.com", role="member")
        request = self.request_for(member, project=str(self.pa.uuid))
        queryset, _ = _filtered_emp_queryset(request)
        found = set(queryset.values_list("uuid", flat=True))
        self.assertIn(self.in_a.uuid, found)
        self.assertIn(self.in_b.uuid, found)
        self.assertIn(self.loose.uuid, found)
