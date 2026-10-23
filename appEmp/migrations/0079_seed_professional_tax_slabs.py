from datetime import date
from decimal import Decimal

from django.db import migrations

# Placeholder slabs from third-party summaries (greytHR, Kredily, ClearTax).
# NOT verified: check every row with the CA and fix them in Django admin.
# effective_from is a placeholder date so the rows apply to every month.
NOTE = "Third-party summary (greytHR, Kredily, ClearTax). Verify with CA."
KARNATAKA_FEB_NOTE = (
    "February 300 not confirmed from the source page; one month a year is 300. "
    "Verify with CA."
)
EFFECTIVE_FROM = date(2000, 1, 1)

# (state, gender, above, up_to, month, amount, note)
SLABS = [
    ("Maharashtra", "M", "0", "7500", None, "0", NOTE),
    ("Maharashtra", "M", "7500", "10000", None, "175", NOTE),
    ("Maharashtra", "M", "10000", None, None, "200", NOTE),
    ("Maharashtra", "M", "10000", None, 2, "300", NOTE),
    ("Maharashtra", "F", "0", "25000", None, "0", NOTE),
    ("Maharashtra", "F", "25000", None, None, "200", NOTE),
    ("Maharashtra", "F", "25000", None, 2, "300", NOTE),
    ("Karnataka", "A", "0", "24999.99", None, "0", NOTE),
    ("Karnataka", "A", "24999.99", None, None, "200", NOTE),
    ("Karnataka", "A", "24999.99", None, 2, "300", KARNATAKA_FEB_NOTE),
    ("West Bengal", "A", "0", "10000", None, "0", NOTE),
    ("West Bengal", "A", "10000", "15000", None, "110", NOTE),
    ("West Bengal", "A", "15000", "25000", None, "130", NOTE),
    ("West Bengal", "A", "25000", "40000", None, "150", NOTE),
    ("West Bengal", "A", "40000", None, None, "200", NOTE),
    ("Telangana", "A", "0", "15000", None, "0", NOTE),
    ("Telangana", "A", "15000", "20000", None, "150", NOTE),
    ("Telangana", "A", "20000", None, None, "200", NOTE),
    ("Gujarat", "A", "0", "12000", None, "0", NOTE),
    ("Gujarat", "A", "12000", None, None, "200", NOTE),
]

# States with no professional tax: one zero slab so payroll does not warn.
NO_PT_STATES = ["Uttar Pradesh", "Delhi", "Haryana", "Rajasthan"]
NO_PT_NOTE = "No professional tax in this state (third-party summary). Verify with CA."


def seed(apps, schema_editor):
    Slab = apps.get_model("appEmp", "ProfessionalTaxSlab")
    rows = list(SLABS) + [
        (state, "A", "0", None, None, "0", NO_PT_NOTE) for state in NO_PT_STATES
    ]
    for state, gender, above, up_to, month, amount, note in rows:
        Slab.objects.get_or_create(
            state=state,
            gender=gender,
            above=Decimal(above),
            up_to=None if up_to is None else Decimal(up_to),
            month=month,
            effective_from=EFFECTIVE_FROM,
            defaults={"amount": Decimal(amount), "effective_to": None, "note": note},
        )


class Migration(migrations.Migration):

    dependencies = [
        ("appEmp", "0078_professional_tax"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
