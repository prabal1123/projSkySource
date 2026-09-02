from django.db import migrations

DEFAULT_FIELDS = [
    dict(field_key="full_name", column_label="Emp Name", display_name="Employee Name",
         target_model="USER", data_type="FULL_NAME", is_required=True, order=1),
    dict(field_key="email", column_label="Mail ID", display_name="Email",
         target_model="USER", data_type="EMAIL", is_required=True, order=2),
    dict(field_key="phone_number", column_label="Mobile No.", display_name="Mobile Number",
         target_model="PROFILE", data_type="PHONE", is_required=False, order=3),
    dict(field_key="designation", column_label="Designation", display_name="Designation",
         target_model="PROFILE", data_type="DESIGNATION_FK", is_required=False, order=4),
    dict(field_key="aadhar_no", column_label="Aadhar No.", display_name="Aadhar Number",
         target_model="PROFILE", data_type="REGEX", is_required=False, order=5,
         validation_regex=r"^\d{12}$", validation_message="Aadhar No. must be exactly 12 digits."),
    dict(field_key="pan_no", column_label="PAN NO.", display_name="PAN Number",
         target_model="PROFILE", data_type="REGEX", is_required=False, order=6,
         validation_regex=r"^[A-Z]{5}\d{4}[A-Z]$",
         validation_message="PAN No. format looks invalid (e.g. ABCDE1234F)."),
    dict(field_key="bank_name", column_label="NAME OF BANK", display_name="Bank Name",
         target_model="PROFILE", data_type="TEXT", is_required=False, order=7),
    dict(field_key="bank_account_no", column_label="Bank A/C No.", display_name="Bank Account No.",
         target_model="PROFILE", data_type="TEXT", is_required=False, order=8),
    dict(field_key="ifsc_no", column_label="IFSC No.", display_name="IFSC Code",
         target_model="PROFILE", data_type="TEXT", is_required=False, order=9),
    dict(field_key="address", column_label="Emp Adress", display_name="Address",
         target_model="PROFILE", data_type="TEXT", is_required=False, order=10),
    dict(field_key="date_hired", column_label="Date of Joining", display_name="Date of Joining",
         target_model="PROFILE", data_type="DATE", is_required=False, order=11),
    dict(field_key="avsec_training_date", column_label="Date of AVSEC Training",
         display_name="AVSEC Training Date", target_model="PROFILE", data_type="DATE",
         is_required=False, order=12),
    dict(field_key="police_verification_date", column_label="Date of Police Verification",
         display_name="Police Verification Date", target_model="PROFILE", data_type="DATE",
         is_required=False, order=13),
    dict(field_key="uan_no", column_label="UAN No.", display_name="UAN Number",
         target_model="PROFILE", data_type="TEXT", is_required=False, order=14),
    dict(field_key="esic_no", column_label="ESIC No.", display_name="ESIC Number",
         target_model="PROFILE", data_type="TEXT", is_required=False, order=15),
]


def seed_fields(apps, schema_editor):
    Config = apps.get_model("appEmp", "EmployeeImportFieldConfig")
    for row in DEFAULT_FIELDS:
        Config.objects.update_or_create(field_key=row["field_key"], defaults=row)


def unseed_fields(apps, schema_editor):
    Config = apps.get_model("appEmp", "EmployeeImportFieldConfig")
    Config.objects.filter(field_key__in=[r["field_key"] for r in DEFAULT_FIELDS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("appEmp", "0041_employeeimportfieldconfig"),  # ← replace with the exact filename makemigrations gave you
    ]

    operations = [
        migrations.RunPython(seed_fields, unseed_fields),
    ]