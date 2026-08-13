from django.db import migrations


def assign_group_permissions(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    permission_map = {
        "HR_ADMIN": [
            "view_hr_dashboard",
            "manage_employees",
            "manage_attendance",
            "review_leave",
            "manage_leave_balance",
            "review_attendance_exception",
            "manage_salary",
        ],

        "RECRUITER": [
            "view_hr_dashboard",
            "manage_employees",
        ],

        "HIRING_MANAGER": [
            "view_hr_dashboard",
            "manage_employees",
            "review_leave",
            "review_attendance_exception",
        ],

        "TEAM_LEAD": [
            "view_hr_dashboard",
            "review_leave",
            "review_attendance_exception",
        ],

        "EMPLOYEE": [],
    }

    for group_name, permission_codenames in permission_map.items():

        group = Group.objects.filter(
            name=group_name
        ).first()

        if not group:
            continue

        permissions = Permission.objects.filter(
            content_type__app_label="appEmp",
            codename__in=permission_codenames,
        )

        group.permissions.add(*permissions)


def remove_group_permissions(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    managed_permissions = Permission.objects.filter(
        content_type__app_label="appEmp",
        codename__in=[
            "view_hr_dashboard",
            "manage_employees",
            "manage_attendance",
            "review_leave",
            "manage_leave_balance",
            "review_attendance_exception",
            "manage_salary",
        ],
    )

    for group in Group.objects.filter(
        name__in=[
            "HR_ADMIN",
            "RECRUITER",
            "HIRING_MANAGER",
            "TEAM_LEAD",
            "EMPLOYEE",
        ]
    ):
        group.permissions.remove(
            *managed_permissions
        )


class Migration(migrations.Migration):

    dependencies = [
        ("appEmp", "0018_alter_empprofile_options"),
    ]

    operations = [
        migrations.RunPython(
            assign_group_permissions,
            remove_group_permissions,
        ),
    ]