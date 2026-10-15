from django.db import migrations


def enable_all(apps, schema_editor):
    from app_organizations.modules import MODULES

    Organization = apps.get_model("app_organizations", "Organization")
    OrganizationModule = apps.get_model("app_organizations", "OrganizationModule")
    for org in Organization.objects.all():
        for key in MODULES:
            OrganizationModule.objects.get_or_create(
                organization=org,
                module_key=key,
                defaults={"is_enabled": True, "source": "manual"},
            )


class Migration(migrations.Migration):
    dependencies = [
        ("app_organizations", "0003_organization_module"),
    ]

    operations = [
        migrations.RunPython(enable_all, migrations.RunPython.noop),
    ]