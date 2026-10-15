"""Payroll Phase 4, step 1: the payslip PDF builder."""
from datetime import date

from appEmp.models import Attendance, PayrollRecord
from appEmp.payroll_service import save_payroll_record
from appEmp.payslip_pdf import build_payslip_pdf
from appEmp.test_payroll_service import MONTH, YEAR, PayrollBase


class PayslipPdfTests(PayrollBase):
    def locked_record(self):
        p = self.employee()
        self.full_attendance(p)
        record = save_payroll_record(self.calc(p))
        record.lock(self.su)
        return p, PayrollRecord.objects.get(pk=record.pk)

    def pdf_bytes(self, record):
        return build_payslip_pdf(record, compress=False).read()

    def test_output_is_a_pdf(self):
        _, record = self.locked_record()
        self.assertTrue(self.pdf_bytes(record).startswith(b"%PDF"))

    def test_slip_shows_the_saved_figures_and_names(self):
        _, record = self.locked_record()
        data = self.pdf_bytes(record)
        self.assertIn(b"55,860.00", data)
        self.assertIn(b"September 2026", data)
        self.assertIn(b"ZZ Org One", data)

    def test_slip_does_not_change_after_attendance_is_edited(self):
        p, record = self.locked_record()
        Attendance.objects.filter(employee=p, date=date(YEAR, MONTH, 9)).delete()
        fresh = PayrollRecord.objects.get(pk=record.pk)
        self.assertIn(b"55,860.00", self.pdf_bytes(fresh))

    def test_unlocked_record_is_refused(self):
        p = self.employee()
        self.full_attendance(p)
        record = save_payroll_record(self.calc(p))
        with self.assertRaises(ValueError):
            build_payslip_pdf(record)
