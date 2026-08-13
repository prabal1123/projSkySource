from django.db import migrations


def migrate_roles_to_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    EmpProfile = apps.get_model("appEmp", "empProfile")

    valid_groups = {
        "HR_ADMIN",
        "RECRUITER",
        "HIRING_MANAGER",
        "TEAM_LEAD",
        "EMPLOYEE",
    }

    for profile in EmpProfile.objects.select_related("user").all():
        user = profile.user

        # Superusers remain controlled by Django is_superuser.
        if user.is_superuser:
            continue

        if profile.role in valid_groups:
            group = Group.objects.filter(
                name=profile.role
            ).first()

            if group:
                user.groups.add(group)


def reverse_groups_migration(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    EmpProfile = apps.get_model("appEmp", "empProfile")

    managed_group_names = [
        "HR_ADMIN",
        "RECRUITER",
        "HIRING_MANAGER",
        "TEAM_LEAD",
        "EMPLOYEE",
    ]

    managed_groups = Group.objects.filter(
        name__in=managed_group_names
    )

    for profile in EmpProfile.objects.select_related("user").all():
        profile.user.groups.remove(*managed_groups)


class Migration(migrations.Migration):

    dependencies = [
        ("appEmp", "0016_create_default_groups"),
    ]

    operations = [
        migrations.RunPython(
            migrate_roles_to_groups,
            reverse_groups_migration,
        ),
    ]

