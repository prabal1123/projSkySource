"""
Phase 2 final cleanup: drop the old plain-text columns.

Before dropping, every encrypted value is read back (so anything unreadable stops
the migration) and every stored value is checked to be ciphertext. The number of
values that differ from their old plain copy is printed; differences are expected
for anything edited or created since the switch, because those changes exist only
in the encrypted columns.

This cannot be undone from inside the database. Reversing the migration recreates
the columns empty; the readable values can only come back from a backup.
Only counts are printed, never values.
"""
from django.db import connection, migrations

TARGETS = (
    (
        "empprofile",
        "empProfile",
        ("aadhar_no", "pan_no", "bank_account_no", "uan_no", "esic_no", "phone_number", "address"),
    ),
    ("salary", "Salary", ("basic_salary", "hra", "pf", "daily_rate")),
    ("wageregisterentry", "WageRegisterEntry", ("rate_override",)),
)


def verify_before_drop(apps, schema_editor):
    differ = 0
    rows = 0
    unmarked = []
    for _key, model_name, names in TARGETS:
        Model = apps.get_model("appEmp", model_name)
        for row in Model.objects.order_by("pk").iterator():
            rows += 1
            for name in names:
                if getattr(row, name) != getattr(row, name + "_legacy"):
                    differ += 1
        table = Model._meta.db_table
        with connection.cursor() as cursor:
            for name in names:
                cursor.execute(
                    'SELECT COUNT(*) FROM "%s" WHERE "%s" IS NOT NULL '
                    "AND \"%s\" <> '' AND \"%s\" NOT LIKE 'enc1:%%'" % (table, name, name, name)
                )
                if cursor.fetchone()[0]:
                    unmarked.append("%s.%s" % (model_name, name))
    if unmarked:
        raise RuntimeError(
            "Nothing was dropped: unencrypted values found in " + ", ".join(unmarked)
        )
    print(
        "\n  checked %d rows, all encrypted values readable; %d values differ from the "
        "old plain copy (expected for anything edited since the switch)" % (rows, differ)
    )


def _drops():
    ops = []
    for key, _model_name, names in TARGETS:
        for name in names:
            ops.append(migrations.RemoveField(model_name=key, name=name + "_legacy"))
    return ops


class Migration(migrations.Migration):

    dependencies = [
        ("appEmp", "0069_phase2_salary_switch_to_encrypted"),
    ]

    operations = [migrations.RunPython(verify_before_drop, migrations.RunPython.noop)] + _drops()
