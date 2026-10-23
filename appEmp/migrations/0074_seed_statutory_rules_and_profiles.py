from datetime import date
from decimal import Decimal

from django.db import migrations

# Start of history. Placeholder date, not a legal effective date.
BEGIN = date(2000, 1, 1)
NEW_PF_CEILING_FROM = date(2026, 9, 17)
NEW_PF_CEILING_NOTE = "EPFO wage ceiling raised to 25000, effective 17 Sep 2026."
SEED_NOTE = "Seeded value. Start date is a placeholder; verify with CA."

RULES = [
    ("EPF_WAGE_CEILING", "15000", BEGIN, date(2026, 9, 16), SEED_NOTE),
    ("EPF_WAGE_CEILING", "25000", NEW_PF_CEILING_FROM, None, NEW_PF_CEILING_NOTE),
    ("EPF_EMPLOYEE_RATE", "0.1200", BEGIN, None, SEED_NOTE),
    ("EPF_EMPLOYER_EPS_RATE", "0.0833", BEGIN, None, SEED_NOTE),
    ("EPF_EMPLOYER_EPF_RATE", "0.0367", BEGIN, None, SEED_NOTE),
    ("EDLI_RATE", "0.0050", BEGIN, None, SEED_NOTE),
    ("EPF_ADMIN_RATE", "0.0050", BEGIN, None, SEED_NOTE),
    ("ESIC_WAGE_CEILING", "21000", BEGIN, None, SEED_NOTE),
    ("ESIC_EMPLOYEE_RATE", "0.0075", BEGIN, None, SEED_NOTE),
    ("ESIC_EMPLOYER_RATE", "0.0325", BEGIN, None, SEED_NOTE),
    ("ESIC_DAILY_WAGE_EXEMPTION", "176", BEGIN, None, SEED_NOTE),
]


def seed(apps, schema_editor):
    StatutoryRule = apps.get_model("appEmp", "StatutoryRule")
    EmployeeStatutoryProfile = apps.get_model("appEmp", "EmployeeStatutoryProfile")
    empProfile = apps.get_model("appEmp", "empProfile")

    for key, value, start, end, note in RULES:
        StatutoryRule.objects.get_or_create(
            key=key,
            effective_from=start,
            defaults={"value": Decimal(value), "effective_to": end, "note": note},
        )

    for emp in empProfile.objects.all():
        EmployeeStatutoryProfile.objects.get_or_create(
            employee=emp,
            defaults={
                "organization_id": emp.organization_id,
                "pf_mode": "FIXED",
                "esi_mode": "FIXED",
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("appEmp", "0073_statutory_rule_and_profile"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
