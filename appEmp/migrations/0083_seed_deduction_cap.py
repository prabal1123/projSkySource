from datetime import date
from decimal import Decimal

from django.db import migrations


def seed(apps, schema_editor):
    Rule = apps.get_model("appEmp", "StatutoryRule")
    Rule.objects.get_or_create(
        key="DEDUCTION_CAP_SHARE",
        effective_from=date(2000, 1, 1),
        defaults={
            "value": Decimal("0.5000"),
            "note": "Total deductions capped at 50% of earned pay; verify with CA",
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("appEmp", "0082_deduction_cap"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
