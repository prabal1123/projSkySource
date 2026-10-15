from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from appEmp.models import empProfile

from .entitlements import seats_left
from .services import create_organization

User = get_user_model()


class SeatLimitBase(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser("root", "root@x.com", "pw")
        self.org, self.owner = create_organization(
            name="Org A", owner_email="a@x.com",
            owner_first_name="A", created_by=self.root,
        )
        from appEmp.models import empProfile as _P
        _P.objects.get_or_create(
            user=self.root, defaults={"organization": self.org}
        )
        self.client.force_login(self.root)
        session = self.client.session
        session["switched_org_id"] = self.org.id
        session.save()
        self.assertEqual(self.client.get(reverse("register")).status_code, 200)

    def used(self):
        return empProfile.objects.filter(organization=self.org, is_active=True).count()

    def set_limit(self, extra):
        self.org.max_employees = None if extra is None else self.used() + extra
        self.org.save()

    def register(self, email):
        return self.client.post(
            reverse("register"),
            {"first_name": "New", "last_name": "Person", "email": email},
        )


class SeatsLeftTests(SeatLimitBase):
    def test_unlimited_by_default(self):
        self.assertIsNone(seats_left(self.org))

    def test_counts_down_and_floors_at_zero(self):
        self.set_limit(2)
        self.assertEqual(seats_left(self.org), 2)
        self.org.max_employees = 0
        self.assertEqual(seats_left(self.org), 0)

    def test_deactivated_employee_frees_a_seat(self):
        self.set_limit(0)
        self.assertEqual(seats_left(self.org), 0)
        empProfile.objects.filter(
            organization=self.org, user=self.owner
        ).update(is_active=False)
        self.assertEqual(seats_left(self.org), 1)


class RegisterLimitTests(SeatLimitBase):
    def test_unlimited_org_can_register(self):
        self.register("n1@x.com")
        self.assertTrue(User.objects.filter(email="n1@x.com").exists())

    def test_blocked_at_the_limit(self):
        self.set_limit(0)
        self.register("n2@x.com")
        self.assertFalse(User.objects.filter(email="n2@x.com").exists())

    def test_last_seat_allowed_then_blocked(self):
        self.set_limit(1)
        self.register("n3@x.com")
        self.assertTrue(User.objects.filter(email="n3@x.com").exists())
        self.register("n4@x.com")
        self.assertFalse(User.objects.filter(email="n4@x.com").exists())


class BulkImportLimitTests(SeatLimitBase):
    def confirm(self, emails):
        session = self.client.session
        session["employee_import_rows"] = [
            {"user_fields": {"email": e, "first_name": "B"}, "profile_fields": {}}
            for e in emails
        ]
        session.save()
        return self.client.post(
            reverse("employeeBulkImport"), {"action": "confirm_import"}
        )

    def test_file_over_the_limit_creates_nothing(self):
        self.set_limit(1)
        self.confirm(["b1@x.com", "b2@x.com"])
        self.assertFalse(User.objects.filter(email="b1@x.com").exists())
        self.assertFalse(User.objects.filter(email="b2@x.com").exists())

    def test_file_within_the_limit_imports(self):
        self.set_limit(2)
        self.confirm(["b3@x.com", "b4@x.com"])
        self.assertTrue(User.objects.filter(email="b3@x.com").exists())
        self.assertTrue(User.objects.filter(email="b4@x.com").exists())

    def test_unlimited_org_imports(self):
        self.confirm(["b5@x.com"])
        self.assertTrue(User.objects.filter(email="b5@x.com").exists())
