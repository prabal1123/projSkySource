from datetime import date
from decimal import Decimal

from django.db import migrations

NOTE = "FY 2025-26 and 2026-27 slabs from third-party summaries; verify with CA"
EFFECTIVE = date(2025, 4, 1)

SLABS = [
    ("NEW", "0", "400000", "0.0000"),
    ("NEW", "400000", "800000", "0.0500"),
    ("NEW", "800000", "1200000", "0.1000"),
    ("NEW", "1200000", "1600000", "0.1500"),
    ("NEW", "1600000", "2000000", "0.2000"),
    ("NEW", "2000000", "2400000", "0.2500"),
    ("NEW", "2400000", None, "0.3000"),
    ("OLD", "0", "250000", "0.0000"),
    ("OLD", "250000", "500000", "0.0500"),
    ("OLD", "500000", "1000000", "0.2000"),
    ("OLD", "1000000", None, "0.3000"),
]

PARAMS = [
    ("TAX_STD_DEDUCTION_NEW", "75000"),
    ("TAX_STD_DEDUCTION_OLD", "50000"),
    ("TAX_REBATE_LIMIT_NEW", "1200000"),
    ("TAX_REBATE_MAX_NEW", "60000"),
    ("TAX_REBATE_LIMIT_OLD", "500000"),
    ("TAX_REBATE_MAX_OLD", "12500"),
    ("TAX_CESS_RATE", "0.04"),
    ("TAX_SURCHARGE_FROM", "5000000"),
]


def seed(apps, schema_editor):
    Slab = apps.get_model("appEmp", "IncomeTaxSlab")
    Rule = apps.get_model("appEmp", "StatutoryRule")
    for regime, above, up_to, rate in SLABS:
        Slab.objects.get_or_create(
            regime=regime,
            above=Decimal(above),
            up_to=None if up_to is None else Decimal(up_to),
            effective_from=EFFECTIVE,
            defaults={"rate": Decimal(rate), "note": NOTE},
        )
    for key, value in PARAMS:
        Rule.objects.get_or_create(
            key=key,
            effective_from=EFFECTIVE,
            defaults={"value": Decimal(value), "note": NOTE},
        )


class Migration(migrations.Migration):

    dependencies = [
        ("appEmp", "0080_income_tax"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
