"""
Phase 2 salary encryption, step 3: switch the app over to the encrypted columns.

1. Re-runs the 0068 backfill (a no-op when everything already matches).
2. Renames the old plain columns to <name>_legacy.
3. Renames the <name>_enc columns to the original names.
4. Makes the legacy columns nullable (new rows no longer write them) and sets the
   final definitions of the encrypted columns.

Reverse: python manage.py migrate appEmp 0068
Writes made after this migration go only to the encrypted columns, so the legacy
plain columns go stale; a rollback does not carry those edits back.
"""
import importlib

from django.db import migrations, models

import appEmp.fields

_backfill_module = importlib.import_module(
    "appEmp.migrations.0068_phase2_salary_backfill_encrypted"
)

SALARY_COLUMNS = ("basic_salary", "hra", "pf", "daily_rate")
WAGE_COLUMNS = ("rate_override",)


def _renames(suffix_from, suffix_to):
    ops = []
    for model_name, columns in (("salary", SALARY_COLUMNS), ("wageregisterentry", WAGE_COLUMNS)):
        for name in columns:
            ops.append(
                migrations.RenameField(model_name, name + suffix_from, name + suffix_to)
            )
    return ops


def _rename_old_to_legacy():
    return _renames("", "_legacy")


def _rename_enc_to_name():
    return _renames("_enc", "")


class Migration(migrations.Migration):

    dependencies = [
        ("appEmp", "0068_phase2_salary_backfill_encrypted"),
    ]

    operations = (
        [migrations.RunPython(_backfill_module.backfill, migrations.RunPython.noop)]
        + _rename_old_to_legacy()
        + _rename_enc_to_name()
        + [
            migrations.AlterField(
                model_name="salary",
                name="basic_salary_legacy",
                field=models.DecimalField(blank=True, decimal_places=2, editable=False, max_digits=12, null=True),
            ),
            migrations.AlterField(
                model_name="salary",
                name="hra_legacy",
                field=models.DecimalField(blank=True, decimal_places=2, editable=False, max_digits=12, null=True),
            ),
            migrations.AlterField(
                model_name="salary",
                name="pf_legacy",
                field=models.DecimalField(blank=True, decimal_places=2, editable=False, max_digits=12, null=True),
            ),
            migrations.AlterField(
                model_name="salary",
                name="daily_rate_legacy",
                field=models.DecimalField(blank=True, decimal_places=2, editable=False, max_digits=10, null=True),
            ),
            migrations.AlterField(
                model_name="wageregisterentry",
                name="rate_override_legacy",
                field=models.DecimalField(blank=True, decimal_places=2, editable=False, max_digits=10, null=True),
            ),
            migrations.AlterField(
                model_name="salary",
                name="basic_salary",
                field=appEmp.fields.EncryptedDecimalField(decimal_places=2, max_digits=12),
            ),
            migrations.AlterField(
                model_name="salary",
                name="hra",
                field=appEmp.fields.EncryptedDecimalField(decimal_places=2, default=0, max_digits=12),
            ),
            migrations.AlterField(
                model_name="salary",
                name="pf",
                field=appEmp.fields.EncryptedDecimalField(decimal_places=2, default=0, max_digits=12),
            ),
            migrations.AlterField(
                model_name="salary",
                name="daily_rate",
                field=appEmp.fields.EncryptedDecimalField(
                    blank=True, decimal_places=2, max_digits=10, null=True,
                    help_text="Only used when wage_type=DAILY. If blank, derived from basic_salary / days in month.",
                ),
            ),
            migrations.AlterField(
                model_name="wageregisterentry",
                name="rate_override",
                field=appEmp.fields.EncryptedDecimalField(
                    blank=True, decimal_places=2, max_digits=10, null=True,
                    help_text="Leave blank to use Salary.get_daily_rate(). Set to override for this month only.",
                ),
            ),
        ]
    )
