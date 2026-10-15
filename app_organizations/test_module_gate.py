from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import OrganizationModule
from .services import create_organization

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
