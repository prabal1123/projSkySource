from django.db import migrations

DEFAULT_ORG_NAME = "yugaamAi"

MODEL_NAMES = [
    "ShiftMaster",
    "DesignationMaster",
    "LeaveTypeMaster",
    "Holiday",
    "DocumentTypeMaster",
    "WorkSchedule",
    "EmployeeImportFieldConfig",
]


def _get_default_org(apps):
    Organization = apps.get_model("app_organizations", "Organization")
    return (
        Organization.objects.filter(name=DEFAULT_ORG_NAME)
        .order_by("id")
        .first()
    )


def backfill_masters_organization(apps, schema_editor):
    org = _get_default_org(apps)

    for model_name in MODEL_NAMES:
        Model = apps.get_model("appEmp", model_name)
        unassigned = Model.objects.filter(organization__isnull=True)

        if not unassigned.exists():
            continue

        if org is None:
            raise RuntimeError(
                f"Default organization '{DEFAULT_ORG_NAME}' not found, but "
                f"{model_name} rows without an organization exist."
            )

        unassigned.update(organization=org)


def unassign_masters_organization(apps, schema_editor):
    org = _get_default_org(apps)
    if org is None:
        return

    for model_name in MODEL_NAMES:
        Model = apps.get_model("appEmp", model_name)
        Model.objects.filter(organization=org).update(organization=None)


class Migration(migrations.Migration):

    dependencies = [
        ("appEmp", "0055_masters_add_organization"),
        ("app_organizations", "0002_seed_default_organization"),
    ]

    operations = [
        migrations.RunPython(
            backfill_masters_organization,
            unassign_masters_organization,
        ),
    ]