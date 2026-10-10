from decimal import Decimal

from cryptography.fernet import Fernet
from django.db import connection
from django.test.utils import override_settings

from appEmp import test_phase2_encryption as common
from appEmp.fields import FieldDecryptionError
from appEmp.models import Salary
from appEmp.models import empProfile as P


class WrongKeyTests(common.Base):
    def test_wrong_key_gives_a_clear_error_without_the_value(self):
        p = self.make(self.org1, "zz_k1@example.com", pan_no="ABCDE1234F", phone_number=common.PHONE_A)
        with override_settings(FIELD_ENCRYPTION_KEYS=[Fernet.generate_key().decode()]):
            with self.assertRaises(FieldDecryptionError) as ctx:
                P.objects.get(pk=p.pk)
        message = str(ctx.exception)
        self.assertNotIn("ABCDE1234F", message)
        self.assertNotIn(common.PHONE_A, message)

    def test_a_plain_value_in_an_encrypted_column_is_refused(self):
        p = self.make(self.org1, "zz_k2@example.com", pan_no="ABCDE1234F")
        with connection.cursor() as cursor:
            cursor.execute('UPDATE "appEmp_empprofile" SET "pan_no" = %s WHERE id = %s', ["ABCDE1234F", p.pk])
        with self.assertRaises(FieldDecryptionError):
            P.objects.get(pk=p.pk)

    def test_salary_read_with_the_wrong_key_is_refused(self):
        profile = self.make(self.org1, "zz_k3@example.com")
        s = Salary.objects.create(employee=profile, basic_salary=Decimal("50000.00"))
        with override_settings(FIELD_ENCRYPTION_KEYS=[Fernet.generate_key().decode()]):
            with self.assertRaises(FieldDecryptionError):
                Salary.objects.get(pk=s.pk)
