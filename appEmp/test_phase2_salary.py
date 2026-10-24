from datetime import date
from decimal import Decimal
from io import StringIO

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import FieldError
from django.core.management import call_command
from django.db import connection
from django.test.utils import override_settings

from appEmp import test_phase2_encryption as common
from appEmp.models import Salary, WageRegisterEntry


def raw_in(table, pk, col):
    with connection.cursor() as cursor:
        cursor.execute('SELECT "%s" FROM "%s" WHERE id = %%s' % (col, table), [pk])
        return cursor.fetchone()[0]


class SalaryEncryptionTests(common.Base):
    def make_salary(self, email, **fields):
        profile = self.make(self.org1, email)
        defaults = {
            "basic_salary": Decimal("50000.00"),
            "hra": Decimal("20000.00"),
            "pf": Decimal("6000.00"),
        }
        defaults.update(fields)
        return Salary.objects.create(employee=profile, **defaults)

    def test_values_are_ciphertext_and_round_trip(self):
        s = self.make_salary("zz_s1@example.com", daily_rate=Decimal("800.00"))
        for col in ("basic_salary", "hra", "pf", "daily_rate"):
            self.assertTrue(raw_in("appEmp_salary", s.pk, col).startswith("enc1:"), col)
        fresh = Salary.objects.get(pk=s.pk)
        self.assertEqual(fresh.basic_salary, Decimal("50000.00"))
        self.assertEqual(fresh.hra, Decimal("20000.00"))
        self.assertEqual(fresh.pf, Decimal("6000.00"))
        self.assertEqual(fresh.daily_rate, Decimal("800.00"))

    def test_calculations_are_unchanged(self):
        s = Salary.objects.get(pk=self.make_salary("zz_s2@example.com").pk)
        self.assertEqual(s.gross_monthly, Decimal("70000.00"))
        self.assertEqual(s.ctc_annual, Decimal("840000.00"))
        self.assertEqual(s.calculate_monthly_tds(), Decimal("0.00"))
        self.assertEqual(s.net_monthly_pay, Decimal("64000.00"))

    def test_daily_rate_from_salary_and_from_daily_wage(self):
        monthly = Salary.objects.get(
            pk=self.make_salary("zz_s3@example.com", basic_salary=Decimal("31000.00")).pk
        )
        self.assertEqual(monthly.get_daily_rate(31), Decimal("1000.00"))
        daily = Salary.objects.get(
            pk=self.make_salary("zz_s4@example.com", wage_type="DAILY", daily_rate=Decimal("800.00")).pk
        )
        self.assertEqual(daily.get_daily_rate(31), Decimal("800.00"))

    def test_wage_register_uses_rate_override_when_set(self):
        s = self.make_salary("zz_s5@example.com", basic_salary=Decimal("31000.00"))
        with_override = WageRegisterEntry.objects.create(
            salary=s, wage_month=date(2026, 10, 1), rate_override=Decimal("950.00")
        )
        without = WageRegisterEntry.objects.create(salary=s, wage_month=date(2026, 12, 1))
        self.assertTrue(
            raw_in("appEmp_wageregisterentry", with_override.pk, "rate_override").startswith("enc1:")
        )
        self.assertIsNone(raw_in("appEmp_wageregisterentry", without.pk, "rate_override"))
        self.assertEqual(WageRegisterEntry.objects.get(pk=with_override.pk).rate_of_wages, Decimal("950.00"))
        self.assertEqual(WageRegisterEntry.objects.get(pk=without.pk).rate_of_wages, Decimal("1000.00"))

    def test_searching_a_salary_field_is_refused(self):
        self.make_salary("zz_s6@example.com")
        with self.assertRaises(FieldError):
            list(Salary.objects.filter(basic_salary__gt=1))

    def test_no_plain_text_legacy_columns_remain(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND column_name ~ %s",
                ["_legacy$"],
            )
            left = cursor.fetchall()
        self.assertEqual(left, [])

    def test_key_rotation_covers_salary_fields(self):
        s = self.make_salary("zz_s8@example.com")
        old_keys = list(settings.FIELD_ENCRYPTION_KEYS)
        new_key = Fernet.generate_key().decode()
        before = raw_in("appEmp_salary", s.pk, "basic_salary")
        with override_settings(FIELD_ENCRYPTION_KEYS=[new_key] + old_keys):
            call_command("rotate_encryption_keys", stdout=StringIO())
        self.assertNotEqual(raw_in("appEmp_salary", s.pk, "basic_salary"), before)
        with override_settings(FIELD_ENCRYPTION_KEYS=[new_key]):
            self.assertEqual(Salary.objects.get(pk=s.pk).basic_salary, Decimal("50000.00"))
