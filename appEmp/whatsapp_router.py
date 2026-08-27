# appEmp/whatsapp_router.py

import re
from appEmp.models import empProfile
from django.utils import timezone

def normalize_phone(raw: str) -> str:
    """Return the last 10 digits of a phone number, stripped of any
    non-digit characters. Used to match WhatsApp sender numbers
    (e.g. '918886588873') against empProfile.phone_number
    (e.g. '08886588873') regardless of prefix formatting."""
    digits = re.sub(r"\D", "", raw or "")
    return digits[-10:] if len(digits) >= 10 else digits


def find_employee_by_phone(sender_number: str):
    """Returns the matching empProfile, or None if there's no match
    or more than one match (ambiguous phone numbers must never
    resolve to a guess — caller should fall back to needs_human)."""
    target = normalize_phone(sender_number)
    if not target:
        return None

    matches = [
        emp for emp in empProfile.objects.exclude(phone_number__isnull=True).exclude(phone_number="")
        if normalize_phone(emp.phone_number) == target
    ]

    if len(matches) == 1:
        return matches[0]

    return None

def get_leave_balance_reply(employee) -> str:
    """
    Build a human-readable leave balance summary for an employee,
    using the current calendar year. Handles employees with zero,
    one, or multiple leave types.
    """
    from datetime import date
    balances = employee.leave_balances.filter(year=date.today().year)

    if not balances.exists():
        return "We couldn't find any leave balance records for you. Please contact HR."

    if balances.count() == 1:
        b = balances.first()
        return f"You have {b.available_balance} day(s) of {b.leave_type} remaining."

    lines = [f"{b.leave_type}: {b.available_balance} day(s)" for b in balances]
    return "Your leave balances:\n" + "\n".join(lines)



CATEGORY_RULES = [
    ("leave", re.compile(r"\bleave\b|\bbalance\b|\bpto\b|\bcasual leave\b|\bsick leave\b", re.I)),
    ("attendance", re.compile(r"\battendance\b|\bpresent\b|\babsent\b|\bcheck.?in\b|\bcheck.?out\b", re.I)),
    ("payroll", re.compile(r"\bsalary\b|\bpayslip\b|\bpay\b|\breimbursement\b", re.I)),
]

def classify_message(message_text: str) -> str:
    """Returns a category string based on keyword rules.
    Falls back to 'general' if nothing matches."""
    for category, pattern in CATEGORY_RULES:
        if pattern.search(message_text or ""):
            return category
    return "general"


def get_attendance_reply(employee) -> str:
    """Reports today's attendance status for the employee."""
    today = timezone.localdate()
    record = employee.attendances.filter(date=today).first()

    if not record:
        return "No attendance has been marked for you today yet."

    if record.check_in and record.check_out:
        return (
            f"Today's status: {record.get_status_display()}. "
            f"Checked in at {record.check_in.strftime('%I:%M %p')}, "
            f"checked out at {record.check_out.strftime('%I:%M %p')}."
        )
    if record.check_in:
        return (
            f"Today's status: {record.get_status_display()}. "
            f"Checked in at {record.check_in.strftime('%I:%M %p')}, no check-out yet."
        )
    return f"Today's status: {record.get_status_display()}."

def get_payroll_reply(employee) -> str:
    """Reports the employee's current net monthly pay only —
    no breakdown of basic/HRA/PF/TDS over WhatsApp."""
    salary = employee.salary_records.filter(is_active=True).first()

    if not salary:
        return "We couldn't find active salary records for you. Please contact HR."

    return f"Your net pay this month is ₹{salary.net_monthly_pay:,.2f}."
