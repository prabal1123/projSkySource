from django.db import migrations


def setup_finance_and_clearance_permissions(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    # Create FINANCE role.
    finance_group, _ = Group.objects.get_or_create(
        name="FINANCE"
    )

    finance_permissions = Permission.objects.filter(
        content_type__app_label="appEmp",
        codename__in=[
            "review_finance_noc",
        ],
    )

    finance_group.permissions.add(
        *finance_permissions
    )

    # Add clearance / exit permissions to HR_ADMIN.
    hr_group = Group.objects.filter(
        name="HR_ADMIN"
    ).first()

    if hr_group:
        hr_permissions = Permission.objects.filter(
            content_type__app_label="appEmp",
            codename__in=[
                "view_all_clearance_requests",
                "apply_clearance_for_employee",
                "initiate_employee_exit",
                "finalize_employee_exit",
            ],
        )

        hr_group.permissions.add(
            *hr_permissions
        )


def remove_finance_and_clearance_permissions(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    hr_permissions = Permission.objects.filter(
        content_type__app_label="appEmp",
        codename__in=[
            "view_all_clearance_requests",
            "apply_clearance_for_employee",
            "initiate_employee_exit",
            "finalize_employee_exit",
        ],
    )

    hr_group = Group.objects.filter(
        name="HR_ADMIN"
    ).first()

    if hr_group:
        hr_group.permissions.remove(
            *hr_permissions
        )

    finance_group = Group.objects.filter(
        name="FINANCE"
    ).first()

    if finance_group:
        finance_group.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("appEmp", "0021_alter_empprofile_options"),
    ]

    operations = [
        migrations.RunPython(
            setup_finance_and_clearance_permissions,
            remove_finance_and_clearance_permissions,
        ),
    ]