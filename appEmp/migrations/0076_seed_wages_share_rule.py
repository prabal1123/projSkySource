from datetime import date
from decimal import Decimal

from django.db import migrations


def seed(apps, schema_editor):
    StatutoryRule = apps.get_model("appEmp", "StatutoryRule")
    StatutoryRule.objects.get_or_create(
        key="WAGES_MIN_SHARE",
        effective_from=date(2000, 1, 1),
        defaults={
            "value": Decimal("0.5000"),
            "effective_to": None,
            "note": "Wages must be at least this share of total pay (50% rule). Verify with CA.",
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("appEmp", "0075_payroll_employer_share"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
