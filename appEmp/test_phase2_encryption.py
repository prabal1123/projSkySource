from io import StringIO
from types import SimpleNamespace
from unittest import mock

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import Group, User
from django.core.exceptions import FieldError, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, transaction
from django.test import RequestFactory, TestCase
from django.test.utils import override_settings
from django.urls import reverse

from app_organizations.models import Organization
from appEmp.blind_index import phone_index
from appEmp.forms import EmployeeForm, ProfileFormAdmin
from appEmp.models import empProfile as P
from appEmp.views import _filtered_emp_queryset
from appEmp.whatsapp_router import find_employee_by_phone

COLS = ["aadhar_no", "pan_no", "bank_account_no", "uan_no", "esic_no", "phone_number", "address"]
AADHAAR_A = "234567890123"
AADHAAR_B = "345678901234"
PHONE_A = "9876500001"


def raw(pk, col):
    with connection.cursor() as cursor:
        cursor.execute('SELECT "%s" FROM "appEmp_empprofile" WHERE id = %%s' % col, [pk])
        return cursor.fetchone()[0]


def raw_all():
    cols = ", ".join('"%s"' % c for c in COLS)
    with connection.cursor() as cursor:
        cursor.execute('SELECT id, %s FROM "appEmp_empprofile" ORDER BY id' % cols)
        return cursor.fetchall()


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


class StorageAndFormTests(Base):
    def test_values_are_stored_as_ciphertext(self):
        p = self.make(self.org1, "zz_a@example.com", aadhar_no=AADHAAR_A, pan_no="ABCDE1234F",
                      bank_account_no="123456789012", uan_no="100200300400", esic_no="5566778899",
                      phone_number=PHONE_A, address="1 Test Street")
        for col in COLS:
            self.assertTrue(raw(p.pk, col).startswith("enc1:"), col)
        fresh = P.objects.get(pk=p.pk)
        self.assertEqual(fresh.aadhar_no, AADHAAR_A)
        self.assertEqual(fresh.address, "1 Test Street")

    def test_employee_form_round_trip(self):
        p = self.make(self.org1, "zz_b@example.com")
        data = {"first_name": "Zz", "last_name": "Test", "email": "zz_b@example.com",
                "phone_number": "9123456780", "state": "", "zip_code": "", "address": "12 Test Street"}
        form = EmployeeForm(data, instance=P.objects.get(pk=p.pk))
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        fresh = P.objects.get(pk=p.pk)
        self.assertEqual(fresh.phone_number, "9123456780")
        self.assertEqual(fresh.address, "12 Test Street")
        self.assertEqual(fresh.phone_bidx, phone_index("9123456780"))
        self.assertEqual(EmployeeForm(instance=fresh).initial.get("phone_number"), "9123456780")

    def test_admin_form_round_trip(self):
        group = Group.objects.create(name="ZZ_TEST_GROUP")
        p = self.make(self.org1, "zz_c@example.com")
        data = {"first_name": "Zz", "last_name": "Test", "email": "zz_c@example.com",
                "access_group": group.pk, "phone_number": "9123456781", "address": "Admin address"}
        form = ProfileFormAdmin(data, instance=P.objects.get(pk=p.pk), request_user=self.su)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["phone_number"], "9123456781")

    def test_save_with_update_fields_leaves_aadhaar_fingerprint_alone(self):
        p = self.make(self.org1, "zz_d@example.com", aadhar_no=AADHAAR_A)
        before = p.aadhar_bidx
        p.pan_no = "ABCDE1234F"
        p.save(update_fields=["pan_no"])
        self.assertEqual(P.objects.get(pk=p.pk).aadhar_bidx, before)
        p.phone_number = PHONE_A
        p.save(update_fields=["phone_number"])
        self.assertEqual(P.objects.get(pk=p.pk).phone_bidx, phone_index(PHONE_A))

    def test_encrypted_columns_refuse_searches(self):
        with self.assertRaises(FieldError):
            list(P.objects.filter(pan_no="x"))
        with self.assertRaises(FieldError):
            list(P.objects.filter(phone_number__icontains="9"))


class AadhaarTests(Base):
    def test_same_number_in_two_orgs_is_refused_by_the_database(self):
        self.make(self.org1, "zz_e@example.com", aadhar_no=AADHAAR_A)
        p2 = self.make(self.org2, "zz_f@example.com")
        spaced = "2345 6789 0123"
        for value in (AADHAAR_A, spaced):
            with self.assertRaises(IntegrityError), transaction.atomic():
                p2.aadhar_no = value
                p2.save()

    def test_clean_refuses_duplicate_without_naming_the_org(self):
        p1 = self.make(self.org1, "zz_g@example.com", aadhar_no=AADHAAR_A)
        p2 = self.make(self.org2, "zz_h@example.com")
        p1.clean()
        p2.aadhar_no = AADHAAR_A
        with self.assertRaises(ValidationError) as ctx:
            p2.clean()
        self.assertNotIn(self.org1.name, " ".join(ctx.exception.messages))

    def test_malformed_aadhaar_is_rejected(self):
        p = self.make(self.org1, "zz_i@example.com")
        p.aadhar_no = "123"
        with self.assertRaises(ValidationError):
            p.save()

    def test_many_profiles_can_have_no_aadhaar(self):
        self.make(self.org1, "zz_j@example.com")
        self.make(self.org2, "zz_k@example.com")
        self.assertEqual(P.objects.filter(aadhar_bidx__isnull=True).count(), 2)


class PhoneTests(Base):
    def test_search_matches_full_number_only(self):
        p = self.make(self.org1, "zz_l@example.com", phone_number=PHONE_A)

        def found(text):
            request = SimpleNamespace(GET={"q": text}, current_org=self.org1)
            return _filtered_emp_queryset(request)[0].filter(pk=p.pk).exists()

        self.assertTrue(found(PHONE_A))
        self.assertTrue(found("+91 98765 00001"))
        self.assertFalse(found("987650"))
        self.assertTrue(found("Zz"))

    def test_router_returns_one_match_or_none(self):
        p1 = self.make(self.org1, "zz_m@example.com", phone_number=PHONE_A)
        self.assertEqual(find_employee_by_phone("91" + PHONE_A), p1)
        self.assertIsNone(find_employee_by_phone("919999900000"))
        self.assertIsNone(find_employee_by_phone("12345"))
        self.assertIsNone(find_employee_by_phone(""))
        self.make(self.org2, "zz_n@example.com", phone_number=PHONE_A)
        self.assertIsNone(find_employee_by_phone("91" + PHONE_A))


class AdminAndImportTests(Base):
    def test_admin_hides_sensitive_fields_from_non_superusers(self):
        staff = User.objects.create(username="zz_staff", is_staff=True)
        model_admin = admin.site._registry[P]

        def fields_for(user):
            request = RequestFactory().get("/")
            request.user = user
            return set(model_admin.get_form(request, None).base_fields)

        self.assertFalse(any(name in fields_for(staff) for name in COLS))
        self.assertTrue(all(name in fields_for(self.su) for name in COLS))
        self.assertIn("state", fields_for(staff))

    def test_bulk_import_skips_a_row_the_database_refuses(self):
        def row(email, aadhaar):
            return {"user_fields": {"email": email, "first_name": "Zz", "last_name": "Import"},
                    "profile_fields": {"aadhar_no": aadhaar} if aadhaar else {}}

        self.client.force_login(self.su)
        session = self.client.session
        session["employee_import_rows"] = [
            row("zz_imp1@example.com", "999999999999"),
            row("zz_imp2@example.com", "999999999999"),
            row("zz_imp3@example.com", None),
        ]
        session.save()
        with mock.patch("appEmp.views._aadhaar_unusable", return_value=False):
            response = self.client.post(reverse("employeeBulkImport"), {"action": "confirm_import"})
        self.assertEqual(response.status_code, 302)
        emails = set(User.objects.filter(email__startswith="zz_imp").values_list("email", flat=True))
        self.assertEqual(emails, {"zz_imp1@example.com", "zz_imp3@example.com"})


class KeyRotationTests(Base):
    def setUp(self):
        self.old_keys = list(settings.FIELD_ENCRYPTION_KEYS)
        self.new_key = Fernet.generate_key().decode()
        self.p = self.make(self.org1, "zz_o@example.com", aadhar_no=AADHAAR_A, pan_no="ABCDE1234F",
                           phone_number=PHONE_A, address="1 Test Street")

    def run_cmd(self, *args):
        out = StringIO()
        call_command("rotate_encryption_keys", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_counts_and_changes_nothing(self):
        before = raw_all()
        with override_settings(FIELD_ENCRYPTION_KEYS=[self.new_key] + self.old_keys):
            text = self.run_cmd("--dry-run")
        self.assertIn("DRY RUN TOTAL", text)
        self.assertNotIn("rotated=0 ", text)
        self.assertEqual(raw_all(), before)

    def test_refuses_when_old_key_is_missing(self):
        before = raw_all()
        with override_settings(FIELD_ENCRYPTION_KEYS=[self.new_key]):
            with self.assertRaises(CommandError):
                self.run_cmd()
        self.assertEqual(raw_all(), before)

    def test_rotation_keeps_data_and_is_safe_to_repeat(self):
        before_raw = raw_all()
        before = P.objects.get(pk=self.p.pk)
        snapshot = tuple(getattr(before, c) for c in COLS) + (before.aadhar_bidx, before.phone_bidx)
        with override_settings(FIELD_ENCRYPTION_KEYS=[self.new_key] + self.old_keys):
            self.run_cmd()
            self.assertNotEqual(raw_all(), before_raw)
            second = self.run_cmd()
        self.assertIn("rotated=0", second)
        with override_settings(FIELD_ENCRYPTION_KEYS=[self.new_key]):
            after = P.objects.get(pk=self.p.pk)
            self.assertEqual(tuple(getattr(after, c) for c in COLS) + (after.aadhar_bidx, after.phone_bidx), snapshot)
