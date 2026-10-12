from datetime import date

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from app_organizations.models import Organization
from app_projects.models import Project
from appEmp.models import empProfile as P


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        User.objects.bulk_create([
            User(username="zz_su", email="zz_su@example.com", is_staff=True, is_superuser=True, password="!")
        ])
        cls.su = User.objects.get(username="zz_su")
        cls.org1 = Organization.objects.create(name="ZZ Org One", created_by=cls.su)
        cls.org2 = Organization.objects.create(name="ZZ Org Two", created_by=cls.su)

    def make(self, org, email, **fields):
        user = User(username=email, email=email, first_name="Zz", last_name="Test")
        user.set_unusable_password()
        user._organization = org
        user.save()
        profile = P.objects.get(user=user)
        if fields:
            for key, value in fields.items():
                setattr(profile, key, value)
            profile.save()
        return profile

    def project(self, org, name="Prayagraj", code="PRY", **fields):
        return Project.objects.create(organization=org, name=name, code=code, **fields)


class ProjectModelTests(Base):
    def test_uuid_is_generated_and_unique(self):
        a = self.project(self.org1, "A", "AAA")
        b = self.project(self.org1, "B", "BBB")
        self.assertIsNotNone(a.uuid)
        self.assertNotEqual(a.uuid, b.uuid)

    def test_name_unique_per_org_case_insensitive(self):
        self.project(self.org1, "Prayagraj", "PRY")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.project(self.org1, "prayagraj", "PRY2")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.project(self.org1, "  PRAYAGRAJ  ", "PRY3")

    def test_same_name_and_code_allowed_in_another_org(self):
        self.project(self.org1, "Prayagraj", "PRY")
        other = self.project(self.org2, "Prayagraj", "PRY")
        self.assertEqual(other.organization_id, self.org2.id)

    def test_code_is_upper_cased_and_unique_per_org(self):
        p = self.project(self.org1, "Prayagraj", "pry")
        p.refresh_from_db()
        self.assertEqual(p.code, "PRY")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.project(self.org1, "Other Name", "PRY")

    def test_end_date_before_start_is_rejected(self):
        p = Project(
            organization=self.org1, name="Dates", code="DT",
            start_date=date(2026, 5, 1), end_date=date(2026, 4, 1),
        )
        with self.assertRaises(ValidationError):
            p.clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            p.save()

    def test_equal_or_missing_dates_are_allowed(self):
        self.project(self.org1, "Same Day", "SD", start_date=date(2026, 5, 1), end_date=date(2026, 5, 1))
        self.project(self.org1, "Open Ended", "OE", start_date=date(2026, 5, 1))
        self.project(self.org1, "No Dates", "ND")

    def test_lead_from_another_org_is_rejected(self):
        outsider = self.make(self.org2, "zz_lead_other@example.com")
        p = Project(organization=self.org1, name="Lead Test", code="LT", lead=outsider)
        with self.assertRaises(ValidationError):
            p.save()
        with self.assertRaises(ValidationError):
            p.clean()

    def test_lead_from_same_org_is_allowed(self):
        lead = self.make(self.org1, "zz_lead_same@example.com")
        p = self.project(self.org1, "Lead OK", "LK", lead=lead)
        self.assertEqual(p.lead_id, lead.id)
        self.assertIn(p, lead.led_projects.all())


class EmployeeProjectTests(Base):
    def test_new_employee_has_no_project(self):
        p = self.make(self.org1, "zz_none@example.com")
        self.assertIsNone(p.project_id)

    def test_employee_can_join_project_of_own_org(self):
        proj = self.project(self.org1)
        emp = self.make(self.org1, "zz_same@example.com", project=proj)
        emp.refresh_from_db()
        self.assertEqual(emp.project_id, proj.id)
        self.assertEqual(list(proj.employees.all()), [emp])

    def test_project_of_another_org_is_rejected_on_full_save(self):
        foreign = self.project(self.org2, "Foreign", "FR")
        emp = self.make(self.org1, "zz_cross1@example.com")
        emp.project = foreign
        with self.assertRaises(ValidationError):
            emp.save()
        emp.refresh_from_db()
        self.assertIsNone(emp.project_id)

    def test_project_of_another_org_is_rejected_with_update_fields(self):
        foreign = self.project(self.org2, "Foreign", "FR")
        emp = self.make(self.org1, "zz_cross2@example.com")
        emp.project = foreign
        with self.assertRaises(ValidationError):
            emp.save(update_fields=["project"])
        emp.refresh_from_db()
        self.assertIsNone(emp.project_id)

    def test_clearing_the_project_is_allowed(self):
        proj = self.project(self.org1)
        emp = self.make(self.org1, "zz_clear@example.com", project=proj)
        emp.project = None
        emp.save(update_fields=["project"])
        emp.refresh_from_db()
        self.assertIsNone(emp.project_id)


class DeleteAndArchiveTests(Base):
    def test_project_with_employees_cannot_be_deleted(self):
        proj = self.project(self.org1)
        self.make(self.org1, "zz_del@example.com", project=proj)
        with self.assertRaises(ProtectedError):
            proj.delete()
        self.assertTrue(Project.objects.filter(pk=proj.pk).exists())

    def test_empty_project_can_be_deleted(self):
        proj = self.project(self.org1)
        proj.delete()
        self.assertFalse(Project.objects.filter(pk=proj.pk).exists())

    def test_archive_keeps_employees_attached(self):
        proj = self.project(self.org1)
        emp = self.make(self.org1, "zz_arch@example.com", project=proj)
        proj.archive()
        proj.refresh_from_db()
        emp.refresh_from_db()
        self.assertEqual(proj.status, Project.STATUS_ARCHIVED)
        self.assertTrue(proj.is_archived)
        self.assertEqual(emp.project_id, proj.id)

    def test_deleting_a_lead_clears_the_lead_not_the_project(self):
        lead = self.make(self.org1, "zz_lead_del@example.com")
        proj = self.project(self.org1, "Lead Del", "LD", lead=lead)
        Project.objects.filter(pk=proj.pk).update(lead=None)
        proj.refresh_from_db()
        self.assertIsNone(proj.lead_id)


class FlashMessageTests(Base):
    def setUp(self):
        self.client.force_login(self.su)
        session = self.client.session
        session["switched_org_id"] = self.org1.id
        session.save()

    def _alert_count_after(self, url_name, project):
        from django.urls import reverse
        response = self.client.post(reverse(url_name, args=[project.uuid]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<div class="sky-calendar-message">')
        return response

    def test_flash_shows_once_after_archive(self):
        project = self.project(self.org1, "Flash One", "FL1")
        response = self._alert_count_after("projectArchive", project)
        self.assertContains(response, 'class="alert alert-', count=1)

    def test_flash_shows_once_after_unarchive(self):
        project = self.project(self.org1, "Flash Two", "FL2")
        project.archive()
        response = self._alert_count_after("projectUnarchive", project)
        self.assertContains(response, 'class="alert alert-', count=1)

    def test_project_pages_do_not_print_messages_themselves(self):
        from django.template.loader import get_template
        for name in ("app_projects/list.html", "app_projects/detail.html"):
            with open(get_template(name).origin.name, encoding="utf-8") as handle:
                self.assertNotIn("{% if messages %}", handle.read(), name)
