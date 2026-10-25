"""Payroll Phase 8a: final settlement (status flow, items, approval, history, statement PDF)."""
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse

from appEmp.models import (
    EmployeeExitRequest,
    FinalSettlement,
    FinalSettlementItem,
    FinalSettlementLog,
)
from appEmp.test_payroll_pdf import pdf_text
from appEmp.test_payroll_service import MONTH, YEAR
from appEmp.test_payroll_views import PayrollViewBase

D = Decimal
HR_USERNAME = "zz_hr@example.com"


class SettlementBase(PayrollViewBase):
    def make_exit(self, status="READY_FOR_FINALIZATION", employee=None, **fields):
        employee = employee or self.full_employee()
        defaults = dict(
            employee=employee, exit_type="RESIGNATION", reason="x", status=status,
            final_last_working_date=date(YEAR, MONTH, 25),
        )
        defaults.update(fields)
        return EmployeeExitRequest.objects.create(**defaults)

    def settlement_url(self, exit_request):
        return reverse("finalSettlement", args=[exit_request.uuid])

    def pdf_url(self, exit_request):
        return reverse("finalSettlementPdf", args=[exit_request.uuid])

    def act(self, exit_request, action, **extra):
        return self.post(action, url=self.settlement_url(exit_request), **extra)

    def started(self):
        exit_request = self.make_exit()
        self.act(exit_request, "create")
        return exit_request, FinalSettlement.objects.get(exit_request=exit_request)

    def add(self, exit_request, kind, label, amount, note=""):
        return self.act(
            exit_request, "add_item", kind=kind, label=label, amount=amount, note=note
        )

    def approved(self):
        exit_request, settlement = self.started()
        self.add(exit_request, "EARNING", "Bonus", "5000")
        self.add(exit_request, "DEDUCTION", "Advance recovery", "2000")
        self.act(exit_request, "approve")
        return exit_request, FinalSettlement.objects.get(pk=settlement.pk)


# ── Starting a settlement ───────────────────────────────────────────────
class StartSettlementTests(SettlementBase):
    def test_a_settlement_starts_as_a_draft_and_is_logged(self):
        exit_request = self.make_exit()
        response = self.act(exit_request, "create")
        settlement = FinalSettlement.objects.get(exit_request=exit_request)
        self.assertEqual(settlement.status, "DRAFT")
        self.assertEqual(settlement.employee_id, exit_request.employee_id)
        self.assertEqual(settlement.organization_id, self.org1.pk)
        self.assertTrue(any("Settlement started" in m for m in self.messages(response)))
        log = FinalSettlementLog.objects.get(settlement=settlement)
        self.assertEqual((log.action, log.user_name), ("CREATED", HR_USERNAME))

    def test_it_can_also_start_after_the_exit_is_completed(self):
        exit_request = self.make_exit(status="COMPLETED")
        self.act(exit_request, "create")
        self.assertTrue(FinalSettlement.objects.filter(exit_request=exit_request).exists())

    def test_an_exit_that_is_not_ready_cannot_start_one(self):
        for status in ("SUBMITTED", "CLEARANCE_IN_PROGRESS", "HR_REJECTED"):
            exit_request = self.make_exit(status=status)
            response = self.act(exit_request, "create")
            self.assertFalse(FinalSettlement.objects.filter(exit_request=exit_request).exists(), status)
            self.assertTrue(any("ready for finalization" in m for m in self.messages(response)), status)

    def test_starting_twice_keeps_one_settlement(self):
        exit_request, _settlement = self.started()
        response = self.act(exit_request, "create")
        self.assertEqual(FinalSettlement.objects.filter(exit_request=exit_request).count(), 1)
        self.assertEqual(FinalSettlementLog.objects.count(), 1)
        self.assertTrue(any("already exists" in m for m in self.messages(response)))

    def test_other_actions_need_a_started_settlement(self):
        exit_request = self.make_exit()
        response = self.add(exit_request, "EARNING", "Bonus", "5000")
        self.assertTrue(any("Start the settlement first" in m for m in self.messages(response)))
        self.assertFalse(FinalSettlementItem.objects.exists())

    def test_the_page_offers_to_start_when_the_exit_is_ready(self):
        exit_request = self.make_exit()
        self.assertContains(self.get(self.settlement_url(exit_request)), "Start settlement")

    def test_the_page_explains_when_the_exit_is_not_ready(self):
        exit_request = self.make_exit(status="SUBMITTED")
        response = self.get(self.settlement_url(exit_request))
        self.assertContains(response, "once the exit is ready for finalization")
        self.assertNotContains(response, "Start settlement")


# ── Items ───────────────────────────────────────────────────────────────
class ItemTests(SettlementBase):
    def test_earnings_and_deductions_give_the_net_payable(self):
        exit_request, settlement = self.started()
        self.add(exit_request, "EARNING", "Bonus", "5000")
        self.add(exit_request, "EARNING", "Arrears", "1500.50")
        response = self.add(exit_request, "DEDUCTION", "Advance recovery", "2000", note="Feb advance")
        fresh = FinalSettlement.objects.get(pk=settlement.pk)
        self.assertEqual(fresh.total_earnings, D("6500.50"))
        self.assertEqual(fresh.total_deductions, D("2000.00"))
        self.assertEqual(fresh.net_payable, D("4500.50"))
        self.assertTrue(any("Item added" in m for m in self.messages(response)))
        self.assertEqual(fresh.items.get(label="Advance recovery").note, "Feb advance")

    def test_the_page_shows_the_items_and_the_net_payable(self):
        exit_request, _settlement = self.started()
        self.add(exit_request, "EARNING", "Bonus", "5000")
        self.add(exit_request, "DEDUCTION", "Advance recovery", "2000")
        response = self.get(self.settlement_url(exit_request))
        self.assertContains(response, "Bonus")
        self.assertContains(response, "Advance recovery")
        self.assertContains(response, "Net payable")
        self.assertContains(response, "3,000.00")

    def test_deductions_above_earnings_show_as_recoverable(self):
        exit_request, settlement = self.started()
        self.add(exit_request, "EARNING", "Bonus", "1000")
        self.add(exit_request, "DEDUCTION", "Laptop not returned", "4000")
        self.assertEqual(FinalSettlement.objects.get(pk=settlement.pk).net_payable, D("-3000.00"))
        response = self.get(self.settlement_url(exit_request))
        self.assertContains(response, "Recoverable from employee")
        self.assertContains(response, "3,000.00")

    def test_bad_items_are_refused(self):
        exit_request, _settlement = self.started()
        cases = [
            ("EARNING", "Bonus", "0", "Enter an amount above zero"),
            ("EARNING", "Bonus", "-5", "Enter an amount above zero"),
            ("EARNING", "Bonus", "abc", "Enter an amount above zero"),
            ("EARNING", "Bonus", "NaN", "Enter an amount above zero"),
            ("EARNING", "Bonus", "", "Enter an amount above zero"),
            ("EARNING", "Bonus", "10000000000", "Enter an amount above zero"),
            ("EARNING", "", "100", "Give the item a name"),
            ("EARNING", "   ", "100", "Give the item a name"),
            ("EARNING", "x" * 101, "100", "Give the item a name"),
            ("OTHER", "Bonus", "100", "earning or a deduction"),
        ]
        for kind, label, amount, expected in cases:
            response = self.add(exit_request, kind, label, amount)
            self.assertTrue(any(expected in m for m in self.messages(response)), (kind, label, amount))
        self.assertFalse(FinalSettlementItem.objects.exists())

    def test_an_item_can_be_removed_while_the_settlement_is_a_draft(self):
        exit_request, settlement = self.started()
        self.add(exit_request, "EARNING", "Bonus", "5000")
        item = settlement.items.get()
        response = self.act(exit_request, "delete_item", item=item.pk)
        self.assertFalse(settlement.items.exists())
        self.assertTrue(any("Item removed" in m for m in self.messages(response)))

    def test_removing_an_unknown_item_is_harmless(self):
        exit_request, settlement = self.started()
        self.add(exit_request, "EARNING", "Bonus", "5000")
        for value in ("999999", "abc", ""):
            response = self.act(exit_request, "delete_item", item=value)
            self.assertTrue(any("not found" in m for m in self.messages(response)), value)
        self.assertEqual(settlement.items.count(), 1)

    def test_an_item_of_another_settlement_cannot_be_removed(self):
        exit_a, _sa = self.started()
        exit_b = self.make_exit()
        self.act(exit_b, "create")
        self.add(exit_b, "EARNING", "Bonus", "5000")
        item = FinalSettlementItem.objects.get()
        self.act(exit_a, "delete_item", item=item.pk)
        self.assertEqual(FinalSettlementItem.objects.count(), 1)

    def test_the_final_month_salary_is_never_an_item(self):
        exit_request, settlement = self.started()
        self.assertFalse(settlement.items.exists())
        self.assertEqual(settlement.net_payable, D("0"))


# ── Approval, freezing, payment and unlocking ───────────────────────────
class ApprovalTests(SettlementBase):
    def test_approving_needs_at_least_one_item(self):
        exit_request, settlement = self.started()
        response = self.act(exit_request, "approve")
        self.assertEqual(FinalSettlement.objects.get(pk=settlement.pk).status, "DRAFT")
        self.assertTrue(any("Add at least one item" in m for m in self.messages(response)))

    def test_approving_freezes_the_settlement_and_is_logged(self):
        exit_request, settlement = self.approved()
        self.assertEqual(settlement.status, "APPROVED")
        self.assertEqual(settlement.approved_by.username, HR_USERNAME)
        self.assertIsNotNone(settlement.approved_at)
        log = FinalSettlementLog.objects.get(settlement=settlement, action="APPROVED")
        self.assertEqual((log.user_name, log.net_payable), (HR_USERNAME, D("3000.00")))

    def test_approving_twice_changes_nothing(self):
        exit_request, settlement = self.approved()
        response = self.act(exit_request, "approve")
        self.assertTrue(any("already approved" in m for m in self.messages(response)))
        self.assertEqual(FinalSettlementLog.objects.filter(action="APPROVED").count(), 1)

    def test_items_cannot_be_added_or_removed_after_approval(self):
        exit_request, settlement = self.approved()
        count = settlement.items.count()
        added = self.add(exit_request, "EARNING", "Late bonus", "100")
        removed = self.act(exit_request, "delete_item", item=settlement.items.first().pk)
        self.assertEqual(settlement.items.count(), count)
        for response in (added, removed):
            self.assertTrue(any("only be changed while the settlement is a draft" in m
                                for m in self.messages(response)))

    def test_the_model_itself_refuses_changes_after_approval(self):
        _exit_request, settlement = self.approved()
        with self.assertRaises(ValidationError):
            FinalSettlementItem.objects.create(
                settlement=settlement, kind="EARNING", label="Sneaky", amount=D("1")
            )
        item = settlement.items.first()
        item.label = "Changed"
        with self.assertRaises(ValidationError):
            item.save()
        with self.assertRaises(ValidationError):
            item.delete()

    def test_only_an_approved_settlement_can_be_marked_paid(self):
        exit_request, settlement = self.started()
        response = self.act(exit_request, "paid")
        self.assertEqual(FinalSettlement.objects.get(pk=settlement.pk).status, "DRAFT")
        self.assertTrue(any("can be marked as paid" in m for m in self.messages(response)))

    def test_marking_paid_is_logged_and_final(self):
        exit_request, settlement = self.approved()
        response = self.act(exit_request, "paid")
        fresh = FinalSettlement.objects.get(pk=settlement.pk)
        self.assertEqual(fresh.status, "PAID")
        self.assertIsNotNone(fresh.paid_at)
        self.assertTrue(any("marked as paid" in m for m in self.messages(response)))
        self.assertTrue(FinalSettlementLog.objects.filter(settlement=fresh, action="PAID").exists())
        again = self.act(exit_request, "paid")
        self.assertTrue(any("can be marked as paid" in m for m in self.messages(again)))

    def test_unlock_needs_a_reason_of_ten_to_255_characters(self):
        exit_request, settlement = self.approved()
        for reason in ("", "   ", "too short", "x" * 256):
            response = self.act(exit_request, "unlock", reason=reason)
            self.assertEqual(FinalSettlement.objects.get(pk=settlement.pk).status, "APPROVED", reason)
            self.assertTrue(any("Give a reason" in m for m in self.messages(response)), reason)
        self.assertFalse(FinalSettlementLog.objects.filter(action="UNLOCKED").exists())

    def test_unlock_with_a_reason_reopens_the_items_and_is_logged(self):
        exit_request, settlement = self.approved()
        self.act(exit_request, "unlock", reason="Advance amount was entered wrongly")
        fresh = FinalSettlement.objects.get(pk=settlement.pk)
        self.assertEqual(fresh.status, "DRAFT")
        self.assertIsNone(fresh.approved_by)
        self.assertIsNone(fresh.approved_at)
        log = FinalSettlementLog.objects.get(settlement=fresh, action="UNLOCKED")
        self.assertEqual(log.reason, "Advance amount was entered wrongly")
        self.add(exit_request, "EARNING", "Correction", "250")
        self.assertEqual(fresh.items.count(), 3)

    def test_a_draft_or_paid_settlement_cannot_be_unlocked(self):
        exit_request, settlement = self.started()
        draft = self.act(exit_request, "unlock", reason="Trying to unlock a draft")
        self.assertTrue(any("not paid can be unlocked" in m for m in self.messages(draft)))
        exit_two, paid = self.approved()
        self.act(exit_two, "paid")
        response = self.act(exit_two, "unlock", reason="Trying to unlock a paid one")
        self.assertEqual(FinalSettlement.objects.get(pk=paid.pk).status, "PAID")
        self.assertTrue(any("not paid can be unlocked" in m for m in self.messages(response)))

    def test_the_history_runs_in_order_and_cannot_be_edited(self):
        exit_request, settlement = self.approved()
        self.act(exit_request, "unlock", reason="Advance amount was entered wrongly")
        self.act(exit_request, "approve")
        self.act(exit_request, "paid")
        actions = list(reversed(list(
            FinalSettlementLog.objects.filter(settlement=settlement).values_list("action", flat=True)
        )))
        self.assertEqual(actions, ["CREATED", "APPROVED", "UNLOCKED", "APPROVED", "PAID"])
        entry = FinalSettlementLog.objects.first()
        entry.reason = "edited"
        with self.assertRaises(ValidationError):
            entry.save()
        with self.assertRaises(ValidationError):
            entry.delete()

    def test_an_unknown_action_changes_nothing(self):
        exit_request, settlement = self.started()
        response = self.act(exit_request, "burn_it_down")
        self.assertTrue(any("Unknown action" in m for m in self.messages(response)))
        self.assertEqual(FinalSettlement.objects.get(pk=settlement.pk).status, "DRAFT")


# ── Reference to the final month's payroll ──────────────────────────────
class ReferenceTests(SettlementBase):
    def test_unlocked_final_month_is_shown_as_not_locked(self):
        exit_request, _settlement = self.started()
        response = self.get(self.settlement_url(exit_request))
        self.assertContains(response, "paid through payroll")
        self.assertContains(response, "not locked yet")

    def test_locked_final_month_shows_its_net_pay(self):
        exit_request = self.make_exit()
        self.post("lock")
        self.act(exit_request, "create")
        response = self.get(self.settlement_url(exit_request))
        self.assertContains(response, "Payroll is locked")
        self.assertContains(response, "September 2026")

    def test_no_reference_without_a_last_working_day(self):
        exit_request = self.make_exit(final_last_working_date=None)
        self.act(exit_request, "create")
        self.assertNotContains(self.get(self.settlement_url(exit_request)), "paid through payroll")


# ── Statement PDF ───────────────────────────────────────────────────────
class StatementPdfTests(SettlementBase):
    def test_a_draft_has_no_statement(self):
        exit_request, _settlement = self.started()
        response = self.client.get(self.pdf_url(exit_request), follow=True)
        self.assertNotEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(any("Approve the settlement" in m for m in self.messages(response)))
        self.assertEqual(response.redirect_chain[-1][0], self.settlement_url(exit_request))

    def test_an_approved_settlement_downloads_as_a_pdf_with_its_figures(self):
        exit_request, _settlement = self.approved()
        response = self.client.get(self.pdf_url(exit_request))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response["Content-Disposition"].startswith('attachment; filename="settlement_'))
        text = pdf_text(response.content)
        for expected in ("Full and Final Settlement", "Bonus", "Advance recovery",
                         "5,000.00", "2,000.00", "Net payable", "3,000.00"):
            self.assertIn(expected, text)
        self.assertIn("Final month salary for September 2026", text)

    def test_a_negative_settlement_is_printed_as_recoverable(self):
        exit_request, _settlement = self.started()
        self.add(exit_request, "DEDUCTION", "Laptop not returned", "4000")
        self.act(exit_request, "approve")
        text = pdf_text(self.client.get(self.pdf_url(exit_request)).content)
        self.assertIn("Recoverable from employee", text)
        self.assertIn("4,000.00", text)

    def test_a_paid_settlement_still_prints(self):
        exit_request, _settlement = self.approved()
        self.act(exit_request, "paid")
        response = self.client.get(self.pdf_url(exit_request))
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_no_statement_exists_before_a_settlement_is_started(self):
        exit_request = self.make_exit()
        response = self.client.get(self.pdf_url(exit_request))
        self.assertEqual(response.status_code, 404)


# ── Access and scoping ──────────────────────────────────────────────────
class SettlementAccessTests(SettlementBase):
    def test_anonymous_users_are_sent_to_login(self):
        exit_request = self.make_exit()
        self.client.logout()
        for url in (self.settlement_url(exit_request), self.pdf_url(exit_request)):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn("login", response.url.lower(), url)

    def test_users_without_the_permission_cannot_view_or_change_anything(self):
        exit_request = self.make_exit()
        nobody = self.make(self.org1, "zz_nobody@example.com")
        self.client.force_login(nobody.user)
        self.assertEqual(self.client.get(self.settlement_url(exit_request)).status_code, 302)
        self.client.post(self.settlement_url(exit_request), {"action": "create"})
        self.assertFalse(FinalSettlement.objects.exists())

    def test_another_organizations_exit_is_not_found(self):
        outsider = self.make(self.org2, "zz_outsider@example.com")
        exit_request = EmployeeExitRequest.objects.create(
            employee=outsider, exit_type="RESIGNATION", reason="x",
            status="READY_FOR_FINALIZATION", final_last_working_date=date(YEAR, MONTH, 25),
        )
        self.assertEqual(self.client.get(self.settlement_url(exit_request)).status_code, 404)
        self.assertEqual(
            self.client.post(self.settlement_url(exit_request), {"action": "create"}).status_code, 404
        )
        self.assertFalse(FinalSettlement.objects.exists())
