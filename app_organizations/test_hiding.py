from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from appEmp.models import empProfile

from .entitlements import grant_modules
from .models import OrganizationModule
from .services import create_organization

User = get_user_model()


class HidingBase(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser("root", "root@x.com", "pw")
        self.org, self.owner = create_organization(
            name="Org A", owner_email="a@x.com",
            owner_first_name="A", created_by=self.root,
        )
        empProfile.objects.get_or_create(
            user=self.owner, defaults={"organization": self.org},
        )
        self.client.force_login(self.owner)

    def page(self, name, keys):
        OrganizationModule.objects.filter(organization=self.org).delete()
        if keys:
            grant_modules(self.org, keys)
        response = self.client.get(reverse(name))
        self.assertEqual(response.status_code, 200)
        return response


class DashboardHidingTests(HidingBase):
    def dash(self, keys):
        response = self.page("dashboard", keys)
        self.assertContains(response, "Total Employees")
        return response

    def test_core_only(self):
        r = self.dash([])
        for text in (
            "Present Today", "On Leave", "Pending Actions", "Pending HR work",
            "Projects overview", "Upcoming holidays", "Attendance records",
            "Leave overview", "hr-row-split",
        ):
            self.assertNotContains(r, text)

    def test_leave_only(self):
        r = self.dash(["leave"])
        self.assertContains(r, "Leave overview")
        self.assertContains(r, "On Leave")
        self.assertContains(r, "Upcoming holidays")
        self.assertContains(r, "Pending HR work")
        self.assertContains(r, "Leave Requests")
        self.assertContains(r, "Optional Holidays")
        self.assertNotContains(r, "Attendance Exceptions")
        self.assertNotContains(r, "Document Review")
        self.assertNotContains(r, "Present Today")
        self.assertNotContains(r, "Attendance records")
        self.assertNotContains(r, "Projects overview")
        self.assertNotContains(r, "hr-row-split-single")

    def test_payroll_only(self):
        r = self.dash(["payroll"])
        self.assertContains(r, "Present Today")
        self.assertContains(r, "Attendance records")
        self.assertNotContains(r, "Leave overview")
        self.assertNotContains(r, "On Leave")
        self.assertNotContains(r, "Projects overview")
        self.assertNotContains(r, "Upcoming holidays")

    def test_projects_only(self):
        r = self.dash(["projects"])
        self.assertContains(r, "Projects overview")
        self.assertContains(r, "hr-row-split-single")
        self.assertNotContains(r, "Pending HR work")
        self.assertNotContains(r, "Pending Actions")
        self.assertNotContains(r, "Upcoming holidays")


class ProfileHidingTests(HidingBase):
    def test_core_only_hides_both_sections(self):
        r = self.page("myProfile", [])
        for text in ('id="salary"', 'href="#salary"', 'id="documents"', 'href="#documents"'):
            self.assertNotContains(r, text)

    def test_payroll_shows_salary_not_documents(self):
        r = self.page("myProfile", ["payroll"])
        self.assertContains(r, 'id="salary"')
        self.assertContains(r, 'href="#salary"')
        self.assertNotContains(r, 'id="documents"')
        self.assertNotContains(r, 'href="#documents"')

    def test_documents_shows_documents_not_salary(self):
        r = self.page("myProfile", ["documents"])
        self.assertContains(r, 'id="documents"')
        self.assertContains(r, 'href="#documents"')
        self.assertNotContains(r, 'id="salary"')
        self.assertNotContains(r, 'href="#salary"')




