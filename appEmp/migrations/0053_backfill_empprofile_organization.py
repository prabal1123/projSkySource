from django.db import migrations

DEFAULT_ORG_NAME = "yugaamAi"


def backfill_empprofile_organization(apps, schema_editor):
    Organization = apps.get_model("app_organizations", "Organization")
    EmpProfile = apps.get_model("appEmp", "empProfile")

    unassigned = EmpProfile.objects.filter(organization__isnull=True)
    if not unassigned.exists():
        return

    org = (
        Organization.objects.filter(name=DEFAULT_ORG_NAME)
        .order_by("id")
        .first()
    )
    if org is None:
        raise RuntimeError(
            f"Default organization '{DEFAULT_ORG_NAME}' not found, but "
            "employee profiles without an organization exist."
        )

    unassigned.update(organization=org)


def unassign_empprofile_organization(apps, schema_editor):
    Organization = apps.get_model("app_organizations", "Organization")
    EmpProfile = apps.get_model("appEmp", "empProfile")

    org = (
        Organization.objects.filter(name=DEFAULT_ORG_NAME)
        .order_by("id")
        .first()
    )
    if org:
        EmpProfile.objects.filter(organization=org).update(organization=None)


class Migration(migrations.Migration):

    dependencies = [
        ("appEmp", "0052_empprofile_add_organization"),
        ("app_organizations", "0002_seed_default_organization"),
    ]

    operations = [
        migrations.RunPython(
            backfill_empprofile_organization,
            unassign_empprofile_organization,
        ),
    ]