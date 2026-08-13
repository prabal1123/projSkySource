from django.db import migrations


def create_default_work_schedule(apps, schema_editor):
    WorkSchedule = apps.get_model(
        "appEmp",
        "WorkSchedule"
    )

    EmpProfile = apps.get_model(
        "appEmp",
        "empProfile"
    )

    schedule, created = WorkSchedule.objects.get_or_create(
        name="Standard 5-Day Week",
        defaults={
            "monday": True,
            "tuesday": True,
            "wednesday": True,
            "thursday": True,
            "friday": True,
            "saturday": False,
            "sunday": False,
            "is_default": True,
            "is_active": True,
        }
    )

    # Ensure it remains the default
    WorkSchedule.objects.exclude(
        pk=schedule.pk
    ).update(
        is_default=False
    )

    schedule.is_default = True
    schedule.is_active = True
    schedule.save()

    # Existing employees
    EmpProfile.objects.filter(
        work_schedule__isnull=True
    ).update(
        work_schedule=schedule
    )


def reverse_default_work_schedule(apps, schema_editor):
    WorkSchedule = apps.get_model(
        "appEmp",
        "WorkSchedule"
    )

    WorkSchedule.objects.filter(
        name="Standard 5-Day Week"
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
            ("appEmp", "0030_empprofile_work_schedule"),
    ]

    operations = [
        migrations.RunPython(
            create_default_work_schedule,
            reverse_default_work_schedule,
        ),
    ]