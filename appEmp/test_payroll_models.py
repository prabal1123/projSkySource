"""Payroll Phase 1: new Salary deduction fields and the PayrollRecord model."""
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction

from appEmp import test_phase2_encryption as common
from appEmp.forms import SalaryForm
from appEmp.models import PayrollRecord, Salary


def raw_in(table, pk, col):
    with connection.cursor() as cursor:
        cursor.execute('SELECT "%s" FROM "%s" WHERE id = %%s' % (col, table), [pk])
        return cursor.fetchone()[0]


class SalaryDeductionFieldTests(common.Base):
    def make_salary(self, email, **fields):
        profile = self.make(self.org1, email)
        defaults = {
            "basic_salary": Decimal("50000.00"),
            "hra": Decimal("20000.00"),
            "pf": Decimal("6000.00"),
        }
        defaults.update(fields)
        return Salary.objects.create(employee=profile, **defaults)

    def test_new_fields_default_to_zero_and_leave_existing_net_pay_unchanged(self):
        s = Salary.objects.get(pk=self.make_salary("zz_p1@example.com").pk)
        self.assertEqual(s.esi, Decimal("0"))
        self.assertEqual(s.other_deductions, Decimal("0"))
        # Same figures as test_phase2_salary.test_calculations_are_unchanged
        self.assertEqual(s.net_monthly_pay, Decimal("60620.00"))

    def test_esi_and_other_deductions_reduce_net_pay_and_are_encrypted(self):
        s = self.make_salary(
            "zz_p2@example.com", esi=Decimal("525.00"), other_deductions=Decimal("100.00")
        )
        for col in ("esi", "other_deductions"):
            self.assertTrue(raw_in("appEmp_salary", s.pk, col).startswith("enc1:"), col)
        fresh = Salary.objects.get(pk=s.pk)
        self.assertEqual(fresh.fixed_deductions_monthly, Decimal("6625.00"))
        self.assertEqual(fresh.total_deductions_monthly, Decimal("10005.00"))  # + TDS 3380
        self.assertEqual(fresh.net_monthly_pay, Decimal("59995.00"))

    def test_salary_form_accepts_new_fields(self):
        form = SalaryForm({
            "basic_salary": "40000", "hra": "10000", "pf": "4800",
            "esi": "375", "other_deductions": "50", "effective_date": "2026-10-01",
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["esi"], Decimal("375"))


class PayrollRecordTests(common.Base):
    def make_record(self, email="zz_r1@example.com", year=2026, month=9, **fields):
        profile = self.make(self.org1, email)
        defaults = dict(
            employee=profile, year=year, month=month,
            period_start=date(year, month, 1), period_end=date(year, month, 30),
            days_in_period=30, basic_salary=Decimal("50000.00"), hra=Decimal("20000.00"),
            gross_monthly=Decimal("70000.00"), gross_earned=Decimal("65000.00"),
            net_pay=Decimal("55000.00"),
        )
        defaults.update(fields)
        return PayrollRecord.objects.create(**defaults)

    def test_organization_comes_from_employee_and_amounts_are_encrypted(self):
        r = self.make_record()
        self.assertEqual(r.organization_id, self.org1.pk)
        for col in ("basic_salary", "gross_earned", "net_pay", "tds"):
            self.assertTrue(raw_in("appEmp_payrollrecord", r.pk, col).startswith("enc1:"), col)
        self.assertEqual(PayrollRecord.objects.get(pk=r.pk).net_pay, Decimal("55000.00"))

    def test_one_record_per_employee_per_month(self):
        r = self.make_record()
        with self.assertRaises(IntegrityError), transaction.atomic():
            PayrollRecord.objects.create(
                employee=r.employee, year=r.year, month=r.month,
                period_start=r.period_start, period_end=r.period_end, days_in_period=30,
            )

    def test_locked_record_rejects_edits_and_deletion(self):
        r = self.make_record()
        r.lock(self.su)
        r = PayrollRecord.objects.get(pk=r.pk)
        self.assertTrue(r.is_locked)
        self.assertEqual(r.locked_by_id, self.su.pk)
        self.assertIsNotNone(r.locked_at)

        r.net_pay = Decimal("1.00")
        with self.assertRaises(ValidationError):
            r.save()
        with self.assertRaises(ValidationError):
            r.save(update_fields=["net_pay"])
        with self.assertRaises(ValidationError):
            r.delete()
        self.assertEqual(PayrollRecord.objects.get(pk=r.pk).net_pay, Decimal("55000.00"))

    def test_payment_details_can_be_recorded_on_a_locked_record(self):
        r = self.make_record()
        r.lock(self.su)
        r.mode_of_payment = "Bank transfer"
        r.payment_date = date(2026, 10, 1)
        r.save(update_fields=["mode_of_payment", "payment_date"])
        self.assertEqual(PayrollRecord.objects.get(pk=r.pk).mode_of_payment, "Bank transfer")

    def test_unlock_allows_recalculation_again(self):
        r = self.make_record()
        r.lock(self.su)
        r.unlock()
        r = PayrollRecord.objects.get(pk=r.pk)
        self.assertFalse(r.is_locked)
        self.assertIsNone(r.locked_by_id)
        r.net_pay = Decimal("54000.00")
        r.save()
        self.assertEqual(PayrollRecord.objects.get(pk=r.pk).net_pay, Decimal("54000.00"))
