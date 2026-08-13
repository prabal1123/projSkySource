from django.db import migrations


def create_default_groups(apps, schema_editor):
    Group = apps.get_model(
        "auth",
        "Group",
    )

    group_names = [
        "HR_ADMIN",
        "RECRUITER",
        "HIRING_MANAGER",
        "TEAM_LEAD",
        "EMPLOYEE",
    ]

    for group_name in group_names:
        Group.objects.get_or_create(
            name=group_name
        )


def remove_default_groups(apps, schema_editor):
    Group = apps.get_model(
        "auth",
        "Group",
    )

    group_names = [
        "HR_ADMIN",
        "RECRUITER",
        "HIRING_MANAGER",
        "TEAM_LEAD",
        "EMPLOYEE",
    ]

    Group.objects.filter(
        name__in=group_names
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("appEmp", "0015_leaverequest"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(
            create_default_groups,
            remove_default_groups,
        ),
    ]