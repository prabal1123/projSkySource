from django.conf import settings
from django.db import migrations

DEFAULT_ORG_NAME = "yugaamAi"


def seed_default_organization(apps, schema_editor):
    User = apps.get_model(settings.AUTH_USER_MODEL)
    Organization = apps.get_model("app_organizations", "Organization")
    OrganizationMember = apps.get_model("app_organizations", "OrganizationMember")
    EmpProfile = apps.get_model("appEmp", "empProfile")

    owner = User.objects.filter(is_superuser=True).order_by("id").first()
    if owner is None:
        if not User.objects.exists():
            # Fresh database: nothing to seed.
            return
        raise RuntimeError(
            "Cannot seed the default organization: users exist but no superuser "
            "was found. Create one (python manage.py createsuperuser) and re-run migrate."
        )

    org, _ = Organization.objects.get_or_create(
        name=DEFAULT_ORG_NAME,
        defaults={"created_by": owner},
    )

    manager_user_ids = set(
        EmpProfile.objects.filter(manager__isnull=False)
        .values_list("manager__user_id", flat=True)
    )

    for user in User.objects.all().order_by("id"):
        if user.id == owner.id:
            role = "owner"
        elif user.is_superuser:
            role = "admin"
        elif user.id in manager_user_ids:
            role = "manager"
        else:
            role = "member"

        OrganizationMember.objects.get_or_create(
            user=user,
            defaults={"organization": org, "role": role},
        )


def unseed_default_organization(apps, schema_editor):
    Organization = apps.get_model("app_organizations", "Organization")
    OrganizationMember = apps.get_model("app_organizations", "OrganizationMember")

    org = Organization.objects.filter(name=DEFAULT_ORG_NAME).first()
    if org:
        OrganizationMember.objects.filter(organization=org).delete()
        org.delete()


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("app_organizations", "0001_initial"),
        ("appEmp", "0051_wageregisterentry"),
    ]

    operations = [
        migrations.RunPython(seed_default_organization, unseed_default_organization),
    ]