"""Payroll Phase 5: navigation, the retired salary slip, and an end-to-end month."""
from datetime import date

from django.urls import reverse

from appEmp.models import Attendance, PayrollRecord
from appEmp.test_payroll_pdf import PdfBase, pdf_text
from appEmp.test_payroll_service import D, MONTH, YEAR, weekdays_of_month
from appEmp.test_payroll_views import AFTER_MONTH, today_is


class NavigationTests(PdfBase):
    def payroll_link(self):
        return f'href="{reverse("payroll")}"'

    def payslips_link(self):
        return f'href="{reverse("myPayslips")}"'

    def dashboard(self, user):
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        return response

    def test_payroll_manager_sees_payroll_and_my_payslips(self):
        response = self.dashboard(self.hr.user)
        self.assertContains(response, self.payroll_link())
        self.assertContains(response, self.payslips_link())

    def test_ordinary_employee_sees_my_payslips_but_not_payroll(self):
        p = self.full_employee()
        response = self.dashboard(p.user)
        self.assertContains(response, self.payslips_link())
        self.assertNotContains(response, self.payroll_link())


class ProfileSalaryBlockTests(PdfBase):
    def test_admin_profile_links_to_payroll_not_the_retired_slip(self):
        p = self.full_employee()
        boss = self.make(self.org1, "zz_boss_prof@example.com")
        boss.user.is_superuser = True
        boss.user.save()
        self.client.force_login(boss.user)
        response = self.client.get(reverse("editProfile", args=[p.uuid]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "View Payroll")
        self.assertNotContains(response, "Download Payslip")

    def test_own_profile_links_to_my_payslips(self):
        p = self.full_employee()
        self.client.force_login(p.user)
        response = self.client.get(reverse("myProfile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "My Payslips")
        self.assertNotContains(response, "Download Payslip")


class RetiredSalarySlipTests(PdfBase):
    """The old slip URLs still work, but now hand over to finalised payroll."""

    def old_self(self):
        return reverse("salarySlipSelf", args=[YEAR, MONTH])

    def old_admin(self, p):
        return reverse("salarySlipAdmin", args=[p.uuid, YEAR, MONTH])

    def test_self_slip_url_delivers_the_finalised_payslip(self):
        p = self.named("Alice")
        self.post("lock")
        self.login_as(p)
        response = self.client.get(self.old_self(), follow=True)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("payslip_", response["Content-Disposition"])
        self.assertIn("58,200.00", pdf_text(response.content))

    def test_self_slip_url_without_finalised_payroll_explains(self):
        p = self.named("Alice")
        self.login_as(p)
        response = self.client.get(self.old_self(), follow=True)
        self.assertNotEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response.redirect_chain[-1][0], reverse("myPayslips"))
        self.assertTrue(any("isn't available yet" in m for m in self.messages(response)))

    def test_admin_slip_url_delivers_or_explains(self):
        p = self.named("Alice")
        response = self.client.get(self.old_admin(p), follow=True)
        self.assertEqual(
            response.redirect_chain[-1][0], reverse("payrollEmployee", args=[YEAR, MONTH, p.uuid])
        )
        self.post("lock")
        response = self.client.get(self.old_admin(p), follow=True)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_admin_slip_url_still_requires_the_salary_permission(self):
        p = self.named("Alice")
        self.post("lock")
        self.login_as(p)
        self.assertRedirects(
            self.client.get(self.old_admin(p)), reverse("dashboard"), fetch_redirect_response=False
        )

    def test_the_retired_builder_is_really_gone(self):
        from appEmp import views

        self.assertFalse(hasattr(views, "_build_salary_slip_pdf"))


class EndToEndMonthTests(PdfBase):
    """One month, three employees, from opening payroll to downloading payslips."""

    def test_full_payroll_month(self):
        self.holiday(date(YEAR, MONTH, 10))
        alice = self.named("Alice")
        bob = self.employee(esi="450", other="100")
        self.full_attendance(bob, skip={9, 22})
        bob.user.first_name = "Bob"
        bob.user.save()
        cara = self.employee()
        self.attend(cara, [d for d in weekdays_of_month() if d.day not in (10, 14, 15)])
        cara.user.first_name = "Cara"
        cara.user.save()
        self.leave(cara, self.paid, date(YEAR, MONTH, 14), date(YEAR, MONTH, 15))

        self.client.force_login(self.hr.user)
        with today_is(AFTER_MONTH):
            landing = self.client.get(reverse("payroll"))
        self.assertEqual(landing.url, self.url)

        roster = self.get()
        net = {
            n: self.row_for(roster, p)["figures"]["net_pay"]
            for n, p in (("alice", alice), ("bob", bob), ("cara", cara))
        }
        self.assertEqual(net, {"alice": D("58200.00"), "bob": D("53650.00"), "cara": D("58200.00")})

        self.post("calculate")
        self.login_as(alice)
        self.assertEqual(self.get(reverse("myPayslips")).context["records"], [])

        self.client.force_login(self.hr.user)
        self.post("lock")
        self.assertEqual(PayrollRecord.objects.filter(is_locked=True).count(), 3)

        summary = pdf_text(self.client.get(self.summary_url()).content)
        self.assertIn("3 employees", summary)
        self.assertIn("176,000.00", summary)
        self.assertIn("170,050.00", summary)

        for profile, name, expected_net in (
            (alice, "Alice", "58,200.00"),
            (bob, "Bob", "53,650.00"),
            (cara, "Cara", "58,200.00"),
        ):
            self.login_as(profile)
            listing = self.get(reverse("myPayslips"))
            self.assertEqual([r.employee_id for r in listing.context["records"]], [profile.pk])
            text = pdf_text(self.get(reverse("myPayslipPdf", args=[YEAR, MONTH])).content)
            self.assertIn(name, text)
            self.assertIn(expected_net, text)
        self.login_as(bob)
        bob_text = pdf_text(self.get(reverse("myPayslipPdf", args=[YEAR, MONTH])).content)
        self.assertIn("Pro-rated: 28 of 30 days", bob_text)

        Attendance.objects.filter(employee=alice, date=date(YEAR, MONTH, 9)).delete()
        self.login_as(alice)
        self.assertIn(
            "58,200.00", pdf_text(self.get(reverse("myPayslipPdf", args=[YEAR, MONTH])).content)
        )
        self.client.force_login(self.hr.user)
        self.assertTrue(self.row_for(self.get(), alice)["stale"])

        alice_page = reverse("payrollEmployee", args=[YEAR, MONTH, alice.uuid])
        self.post("unlock", url=alice_page)
        self.login_as(alice)
        self.assertEqual(self.get(reverse("myPayslips")).context["records"], [])
        self.login_as(bob)
        self.assertEqual(len(self.get(reverse("myPayslips")).context["records"]), 1)

        self.client.force_login(self.hr.user)
        self.post("lock", url=alice_page)
        self.login_as(alice)
        text = pdf_text(self.get(reverse("myPayslipPdf", args=[YEAR, MONTH])).content)
        self.assertIn("Pro-rated: 29 of 30 days", text)
        self.assertIn("58,000.00", text)
        self.assertIn("56,200.00", text)
        record = PayrollRecord.objects.get(employee=alice)
        self.assertEqual((record.gross_earned, record.net_pay), (D("58000.00"), D("56200.00")))
