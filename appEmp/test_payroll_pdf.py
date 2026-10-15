"""Payroll Phase 4: payslip views, the month summary and My Payslips."""
import base64
import re
import zlib
from datetime import date

from django.contrib.auth.models import User
from django.urls import reverse

from app_organizations.entitlements import grant_modules
from appEmp.models import Attendance, PayrollRecord, empProfile
from appEmp.test_payroll_service import MONTH, YEAR
from appEmp.test_payroll_views import PayrollViewBase


def pdf_text(content):
    """Text drawn on a ReportLab PDF (streams are ASCII85 + Flate by default)."""
    assert content.startswith(b"%PDF"), "not a PDF"
    lines = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", content, re.S):
        data = match.group(1).strip()
        try:
            if data.endswith(b"~>"):
                data = base64.a85decode(data[:-2])
            data = zlib.decompress(data)
        except Exception:
            continue
        for chunk in re.findall(rb"\(((?:[^()\\]|\\.)*)\)\s*Tj", data):
            lines.append(chunk.decode("latin-1").replace("\\(", "(").replace("\\)", ")"))
    return "\n".join(lines)


class PdfBase(PayrollViewBase):
    def named(self, first, **kwargs):
        p = self.full_employee(**kwargs)
        p.user.first_name = first
        p.user.save()
        return p

    def payslip_url(self, p):
        return reverse("payrollPayslip", args=[YEAR, MONTH, p.uuid])

    def summary_url(self):
        return reverse("payrollSummaryPdf", args=[YEAR, MONTH])

    def login_as(self, profile):
        self.client.force_login(profile.user)


class AdminPayslipTests(PdfBase):
    def test_locked_payslip_is_a_pdf_with_the_locked_figures(self):
        p = self.named("Alice")
        self.post("lock")
        response = self.client.get(self.payslip_url(p))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response["Content-Disposition"].startswith('attachment; filename="payslip_'))
        text = pdf_text(response.content)
        for expected in ("Payslip", "September 2026", "Alice", "60,000.00", "4,140.00", "55,860.00"):
            self.assertIn(expected, text)

    def test_not_locked_means_no_payslip(self):
        p = self.full_employee()
        response = self.client.get(self.payslip_url(p), follow=True)
        self.assertNotEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(any("only after payroll" in m for m in self.messages(response)))
        self.assertEqual(
            response.redirect_chain[-1][0], reverse("payrollEmployee", args=[YEAR, MONTH, p.uuid])
        )

    def test_unlocking_withdraws_the_payslip(self):
        p = self.full_employee()
        self.post("lock")
        self.post("unlock")
        self.assertEqual(self.client.get(self.payslip_url(p)).status_code, 302)

    def test_payslip_never_changes_after_locking(self):
        p = self.named("Alice")
        self.post("lock")
        Attendance.objects.filter(employee=p, date=date(YEAR, MONTH, 9)).delete()
        text = pdf_text(self.client.get(self.payslip_url(p)).content)
        self.assertIn("55,860.00", text)
        self.assertNotIn("Pro-rated", text)

    def test_access_rules(self):
        p = self.full_employee()
        self.post("lock")
        foreign = self.make(self.org2, "zz_foreign3@example.com")
        self.assertEqual(self.client.get(self.payslip_url(foreign)).status_code, 404)
        self.assertEqual(
            self.client.get(reverse("payrollPayslip", args=[YEAR, 13, p.uuid])).status_code, 404
        )
        self.login_as(p)
        self.assertRedirects(
            self.client.get(self.payslip_url(p)), reverse("dashboard"), fetch_redirect_response=False
        )


class SummaryPdfTests(PdfBase):
    def test_summary_lists_only_locked_employees_with_totals(self):
        self.named("Alice")
        self.named("Bob", basic="30000", hra="10000")
        self.post("lock")
        late = self.named("Zed")
        self.post("calculate")
        self.assertTrue(PayrollRecord.objects.filter(employee=late, is_locked=False).exists())
        response = self.client.get(self.summary_url())
        self.assertEqual(response["Content-Type"], "application/pdf")
        text = pdf_text(response.content)
        for expected in ("Payroll Summary", "September 2026", "Alice", "Bob", "2 employees", "Total"):
            self.assertIn(expected, text)
        self.assertNotIn("Zed", text)
        records = list(PayrollRecord.objects.filter(is_locked=True))
        self.assertIn(f"{sum(r.net_pay for r in records):,.2f}", text)

    def test_nothing_locked_redirects_back_with_a_message(self):
        self.full_employee()
        self.post("calculate")
        response = self.client.get(self.summary_url(), follow=True)
        self.assertEqual(response.redirect_chain[-1][0], reverse("payrollCycle", args=[YEAR, MONTH]))
        self.assertTrue(any("no locked payroll" in m.lower() for m in self.messages(response)))

    def test_requires_payroll_permission(self):
        self.full_employee()
        self.post("lock")
        nobody = self.make(self.org1, "zz_nobody2@example.com")
        self.login_as(nobody)
        self.assertRedirects(
            self.client.get(self.summary_url()), reverse("dashboard"), fetch_redirect_response=False
        )


class MyPayslipsTests(PdfBase):
    def test_employee_sees_only_their_own_finalised_payslips(self):
        a, b = self.named("Alice"), self.named("Bob")
        self.post("lock")
        self.login_as(a)
        response = self.client.get(reverse("myPayslips"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r.employee_id for r in response.context["records"]], [a.pk])
        self.assertContains(response, "September 2026")

    def test_drafts_are_not_listed(self):
        a = self.named("Alice")
        self.post("calculate")
        self.login_as(a)
        response = self.client.get(reverse("myPayslips"))
        self.assertEqual(response.context["records"], [])
        self.assertContains(response, "No payslips yet")

    def test_employee_can_download_only_their_own_payslip(self):
        a, b = self.named("Alice"), self.named("Bob")
        self.post("lock")
        self.login_as(a)
        response = self.client.get(reverse("myPayslipPdf", args=[YEAR, MONTH]))
        self.assertEqual(response["Content-Type"], "application/pdf")
        text = pdf_text(response.content)
        self.assertIn("Alice", text)
        self.assertNotIn("Bob", text)
        self.assertIn("55,860.00", text)

    def test_month_without_a_finalised_payslip_is_refused(self):
        a = self.named("Alice")
        self.login_as(a)
        response = self.client.get(reverse("myPayslipPdf", args=[YEAR, MONTH]), follow=True)
        self.assertNotEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response.redirect_chain[-1][0], reverse("myPayslips"))
        self.assertTrue(any("isn't available yet" in m for m in self.messages(response)))

    def test_user_without_a_profile_or_organization_is_blocked_by_the_gate(self):
        ghost = User.objects.create_user("zz_ghost", "zz_ghost@example.com", "pw")
        empProfile.objects.filter(user=ghost).delete()
        self.client.force_login(ghost)
        for url in (reverse("myPayslips"), reverse("myPayslipPdf", args=[YEAR, MONTH])):
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_login_is_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("myPayslips")).status_code, 302)


class ModuleGateTests(PdfBase):
    def test_new_urls_are_blocked_when_payroll_is_not_bought(self):
        p = self.full_employee()
        self.post("lock")
        from app_organizations.models import OrganizationModule
        OrganizationModule.objects.filter(organization=self.org1).delete()
        self.client.raise_request_exception = False
        self.assertEqual(self.client.get(self.payslip_url(p)).status_code, 403)
        self.assertEqual(self.client.get(self.summary_url()).status_code, 403)
        self.assertEqual(self.client.get(reverse("myPayslips")).status_code, 403)
        self.assertEqual(self.client.get(reverse("myPayslipPdf", args=[YEAR, MONTH])).status_code, 403)
        grant_modules(self.org1, ["payroll"])
        self.assertEqual(self.client.get(self.payslip_url(p)).status_code, 200)
