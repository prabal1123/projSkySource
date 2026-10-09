"""
Phase 2, step 2.5b: switch the app over to the encrypted columns.

1. Re-runs the 0065 backfill (a no-op when everything already matches).
2. Renames the old plain columns to <name>_legacy.
3. Renames the <name>_enc columns to the original names.
4. Makes aadhar_bidx unique (many NULLs are allowed).

Reverse: python manage.py migrate appEmp 0065
Writes made after this migration go only to the encrypted columns, so the
legacy plain columns go stale; a rollback does not carry those edits back.
"""
import importlib

from django.db import migrations, models

import appEmp.fields

_backfill_module = importlib.import_module(
    "appEmp.migrations.0065_phase2_backfill_encrypted"
)

COLUMNS = (
    "aadhar_no",
    "pan_no",
    "bank_account_no",
    "uan_no",
    "esic_no",
    "phone_number",
    "address",
)


def _rename_old_to_legacy():
    return [
        migrations.RenameField("empprofile", name, name + "_legacy")
        for name in COLUMNS
    ]


def _rename_enc_to_name():
    return [
        migrations.RenameField("empprofile", name + "_enc", name)
        for name in COLUMNS
    ]


class Migration(migrations.Migration):

    dependencies = [
        ("appEmp", "0065_phase2_backfill_encrypted"),
    ]

    operations = (
        [migrations.RunPython(_backfill_module.backfill, migrations.RunPython.noop)]
        + _rename_old_to_legacy()
        + _rename_enc_to_name()
        + [
            migrations.AlterField(
                model_name="empprofile",
                name="aadhar_no_legacy",
                field=models.CharField(blank=True, editable=False, help_text="12-digit Aadhar number.", max_length=20, null=True, unique=True),
            ),
            migrations.AlterField(
                model_name="empprofile",
                name="pan_no_legacy",
                field=models.CharField(blank=True, editable=False, help_text="PAN number, e.g. ABCDE1234F.", max_length=10, null=True),
            ),
            migrations.AlterField(
                model_name="empprofile",
                name="bank_account_no_legacy",
                field=models.CharField(blank=True, editable=False, max_length=30, null=True),
            ),
            migrations.AlterField(
                model_name="empprofile",
                name="uan_no_legacy",
                field=models.CharField(blank=True, editable=False, help_text="Universal Account Number (EPFO).", max_length=20, null=True),
            ),
            migrations.AlterField(
                model_name="empprofile",
                name="esic_no_legacy",
                field=models.CharField(blank=True, editable=False, max_length=20, null=True),
            ),
            migrations.AlterField(
                model_name="empprofile",
                name="phone_number_legacy",
                field=models.CharField(blank=True, editable=False, max_length=15, null=True),
            ),
            migrations.AlterField(
                model_name="empprofile",
                name="address_legacy",
                field=models.TextField(blank=True, editable=False, null=True),
            ),
            migrations.AlterField(
                model_name="empprofile",
                name="aadhar_no",
                field=appEmp.fields.EncryptedCharField(blank=True, help_text="12-digit Aadhar number.", max_length=20, null=True),
            ),
            migrations.AlterField(
                model_name="empprofile",
                name="pan_no",
                field=appEmp.fields.EncryptedCharField(blank=True, help_text="PAN number, e.g. ABCDE1234F.", max_length=10, null=True),
            ),
            migrations.AlterField(
                model_name="empprofile",
                name="bank_account_no",
                field=appEmp.fields.EncryptedCharField(blank=True, max_length=30, null=True),
            ),
            migrations.AlterField(
                model_name="empprofile",
                name="uan_no",
                field=appEmp.fields.EncryptedCharField(blank=True, help_text="Universal Account Number (EPFO).", max_length=20, null=True),
            ),
            migrations.AlterField(
                model_name="empprofile",
                name="esic_no",
                field=appEmp.fields.EncryptedCharField(blank=True, max_length=20, null=True),
            ),
            migrations.AlterField(
                model_name="empprofile",
                name="phone_number",
                field=appEmp.fields.EncryptedCharField(blank=True, max_length=15, null=True),
            ),
            migrations.AlterField(
                model_name="empprofile",
                name="address",
                field=appEmp.fields.EncryptedTextField(blank=True, null=True),
            ),
            migrations.AlterField(
                model_name="empprofile",
                name="aadhar_bidx",
                field=models.CharField(blank=True, editable=False, max_length=64, null=True, unique=True),
            ),
        ]
    )
