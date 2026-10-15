from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import OrganizationModule
from .services import create_organization
from django.urls import URLPattern, URLResolver, get_resolver

from .entitlements import grant_modules
from .modules import CORE_URL_NAMES, module_for_view

User = get_user_model()


class ProjectsGateTests(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser("root", "root@x.com", "pw")
        self.org_a, self.owner_a = create_organization(
            name="Org A", owner_email="a@x.com",
            owner_first_name="A", created_by=self.root,
        )
        self.org_b, self.owner_b = create_organization(
            name="Org B", owner_email="b@x.com",
            owner_first_name="B", created_by=self.root,
        )

    def _get(self, user, name):
        self.client.force_login(user)
        return self.client.get(reverse(name))

    def test_off_by_default_returns_403(self):
        self.assertEqual(self._get(self.owner_a, "projectList").status_code, 403)
        self.assertEqual(self._get(self.owner_a, "myActions").status_code, 403)

    def test_on_is_not_blocked(self):
        OrganizationModule.objects.create(organization=self.org_a, module_key="projects")
        self.assertNotEqual(self._get(self.owner_a, "projectList").status_code, 403)

    def test_two_orgs_differ(self):
        OrganizationModule.objects.create(organization=self.org_a, module_key="projects")
        self.assertNotEqual(self._get(self.owner_a, "projectList").status_code, 403)
        self.assertEqual(self._get(self.owner_b, "projectList").status_code, 403)

    def test_expired_row_is_blocked(self):
        OrganizationModule.objects.create(
            organization=self.org_a, module_key="projects",
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.assertEqual(self._get(self.owner_a, "projectList").status_code, 403)

    def test_disabled_row_is_blocked(self):
        OrganizationModule.objects.create(
            organization=self.org_a, module_key="projects", is_enabled=False,
        )
        self.assertEqual(self._get(self.owner_a, "projectList").status_code, 403)

    def test_superuser_passes_even_when_module_is_off(self):
        self.client.force_login(self.root)
        session = self.client.session
        session["switched_org_id"] = self.org_a.pk  # org_a has no Projects row
        session.save()
        self.assertNotEqual(self.client.get(reverse("projectList")).status_code, 403)



class AppEmpGateTests(TestCase):
    def setUp(self):
        self.client.raise_request_exception = False  # a 500 is not a 403
        self.root = User.objects.create_superuser("root", "root@x.com", "pw")
        self.org, self.owner = create_organization(
            name="Org A", owner_email="a@x.com",
            owner_first_name="A", created_by=self.root,
        )
        self.client.force_login(self.owner)

    def status(self, name, *args):
        return self.client.get(reverse(name, args=args)).status_code

    def test_nothing_bought_blocks_leave_holidays_attendance_payroll(self):
        for name in ["applyLeave", "holidayList", "checkinCheckout",
                     "bcasPassDashboard", "submitResignation",
                     "upload_document", "employeeBulkImport"]:
            self.assertEqual(self.status(name), 403, name)
        self.assertEqual(self.status("salarySlipSelf", 2026, 1), 403)

    def test_leave_brings_holidays_but_not_attendance(self):
        grant_modules(self.org, ["leave"])
        self.assertNotEqual(self.status("applyLeave"), 403)
        self.assertNotEqual(self.status("holidayList"), 403)
        self.assertEqual(self.status("checkinCheckout"), 403)

    def test_payroll_brings_attendance_but_not_leave(self):
        grant_modules(self.org, ["payroll"])
        self.assertNotEqual(self.status("salarySlipSelf", 2026, 1), 403)
        self.assertNotEqual(self.status("checkinCheckout"), 403)
        self.assertEqual(self.status("applyLeave"), 403)

    def test_bcas_brings_documents(self):
        grant_modules(self.org, ["bcas"])
        self.assertNotEqual(self.status("bcasPassDashboard"), 403)
        self.assertNotEqual(self.status("upload_document"), 403)


def _all_routes(patterns):
    for p in patterns:
        if isinstance(p, URLResolver):
            yield from _all_routes(p.url_patterns)
        elif isinstance(p, URLPattern) and p.name:
            yield p.name, p.callback


class UrlCoverageTests(TestCase):
    def test_every_url_is_core_or_in_a_module(self):
        missing = []
        for name, callback in _all_routes(get_resolver().url_patterns):
            if (callback.__module__ or "").startswith("django."):
                continue  # admin, password reset, redirects
            if name in CORE_URL_NAMES:
                continue
            if module_for_view(callback, name) is None:
                missing.append(name)
        self.assertEqual(sorted(set(missing)), [], "URL names with no module")

class SidebarGateTests(TestCase):
    def setUp(self):
        self.client.raise_request_exception = False
        self.root = User.objects.create_superuser("root", "root@x.com", "pw")
        self.org, _ = create_organization(
            name="Org A", owner_email="a@x.com",
            owner_first_name="A", created_by=self.root,
        )
        self.client.force_login(self.root)
        session = self.client.session
        session["switched_org_id"] = self.org.pk
        session.save()

    def page(self):
        response = self.client.get(reverse("employeeList"))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def link(self, name):
        return f'href="{reverse(name)}"'

    def test_nothing_bought_hides_module_links(self):
        html = self.page()
        for name in ["pendingLeaveRequests", "holidayList", "workScheduleList",
                     "bcasPassDashboard", "hr_document_list",
                     "pendingResignations", "employeeBulkImport"]:
            self.assertNotIn(self.link(name), html, name)

    def test_leave_shows_leave_and_holidays_only(self):
        grant_modules(self.org, ["leave"])
        html = self.page()
        self.assertIn(self.link("pendingLeaveRequests"), html)
        self.assertIn(self.link("holidayList"), html)
        self.assertNotIn(self.link("workScheduleList"), html)
        self.assertNotIn(self.link("pendingResignations"), html)

    def test_all_modules_show_everything(self):
        grant_modules(self.org)
        html = self.page()
        for name in ["pendingLeaveRequests", "holidayList", "workScheduleList",
                     "bcasPassDashboard", "hr_document_list",
                     "pendingResignations", "employeeBulkImport"]:
            self.assertIn(self.link(name), html, name)
