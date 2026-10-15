import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from appEmp import views as emp_views
from appEmp.models import WhatsAppTicket, empProfile
from appEmp.whatsapp_router import (
    NOT_ENABLED_REPLY,
    category_enabled,
    find_employee_by_phone,
)

from .entitlements import grant_modules, org_modules
from .models import OrganizationModule
from .services import create_organization

User = get_user_model()

PHONE = "9123456780"
SENDER = "91" + PHONE


class WhatsAppGateBase(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser("root", "root@x.com", "pw")
        self.org, self.owner = create_organization(
            name="Org A", owner_email="a@x.com",
            owner_first_name="A", created_by=self.root,
        )
        self.profile, _ = empProfile.objects.get_or_create(
            user=self.owner, defaults={"organization": self.org},
        )
        self.profile.phone_number = PHONE
        self.profile.save()
        OrganizationModule.objects.filter(organization=self.org).delete()
        found = find_employee_by_phone(SENDER)
        self.assertIsNotNone(found)
        self.assertEqual(found.pk, self.profile.pk)

    def modules(self, keys):
        OrganizationModule.objects.filter(organization=self.org).delete()
        if keys:
            grant_modules(self.org, keys)
        return org_modules(self.org)


class CategoryEnabledTests(WhatsAppGateBase):
    def check(self, keys, leave, attendance, payroll):
        self.modules(keys)
        employee = find_employee_by_phone(SENDER)
        self.assertEqual(category_enabled(employee, "leave"), leave)
        self.assertEqual(category_enabled(employee, "attendance"), attendance)
        self.assertEqual(category_enabled(employee, "payroll"), payroll)
        self.assertTrue(category_enabled(employee, "general"))

    def test_nothing_bought(self):
        self.check([], False, False, False)

    def test_leave_only(self):
        self.check(["leave"], True, False, False)

    def test_payroll_brings_attendance(self):
        self.check(["payroll"], False, True, True)

    def test_attendance_alone_does_not_give_payroll(self):
        self.check(["attendance"], False, True, False)


class WebhookGateTests(WhatsAppGateBase):
    def post(self, text, message_id="wamid.1"):
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "id": message_id,
                            "from": SENDER,
                            "text": {"body": text},
                        }],
                        "contacts": [{"profile": {"name": "Tester"}}],
                    }
                }]
            }]
        }
        request = RequestFactory().post(
            "/whatsapp/", data=json.dumps(payload), content_type="application/json"
        )
        return emp_views.whatsapp_webhook(request)

    def run_message(self, text, keys):
        self.modules(keys)
        with mock.patch.object(emp_views, "send_whatsapp_message") as send, \
                mock.patch.object(
                    emp_views, "get_leave_balance_reply", return_value="LEAVE DATA"
                ) as leave_reply, \
                mock.patch.object(
                    emp_views, "get_payroll_reply", return_value="PAY DATA"
                ) as pay_reply:
            response = self.post(text)
        self.assertEqual(response.status_code, 200)
        return send, leave_reply, pay_reply

    def test_leave_message_blocked_without_leave(self):
        send, leave_reply, _ = self.run_message("leave balance", ["payroll"])
        leave_reply.assert_not_called()
        send.assert_called_once_with(SENDER, NOT_ENABLED_REPLY)
        ticket = WhatsAppTicket.objects.get(wa_message_id="wamid.1")
        self.assertEqual(ticket.status, "auto_resolved")

    def test_leave_message_answered_with_leave(self):
        send, leave_reply, _ = self.run_message("leave balance", ["leave"])
        leave_reply.assert_called_once()
        send.assert_called_once_with(SENDER, "LEAVE DATA")

    def test_salary_message_blocked_without_payroll(self):
        send, _, pay_reply = self.run_message("my salary", ["attendance"])
        pay_reply.assert_not_called()
        send.assert_called_once_with(SENDER, NOT_ENABLED_REPLY)

    def test_salary_message_answered_with_payroll(self):
        send, _, pay_reply = self.run_message("my salary", ["payroll"])
        pay_reply.assert_called_once()
        send.assert_called_once_with(SENDER, "PAY DATA")

    def test_general_message_still_creates_ticket_reply(self):
        send, _, _ = self.run_message("hello there", [])
        args = send.call_args[0]
        self.assertIn("logged your message as ticket", args[1])
