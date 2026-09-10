from django.db import migrations
import datetime


SHIFTS = [
    {
        "name": "General Shift",
        "start_time": datetime.time(9, 0),
        "end_time": datetime.time(18, 0),
        "is_night_shift": False,
        "grace_period_minutes": 10,
        "is_default": True,
    },
    {
        "name": "Night Shift",
        "start_time": datetime.time(22, 0),
        "end_time": datetime.time(6, 0),
        "is_night_shift": True,
        "grace_period_minutes": 10,
        "is_default": False,
    },
]


def seed_shifts(apps, schema_editor):
    ShiftMaster = apps.get_model('appEmp', 'ShiftMaster')
    for shift in SHIFTS:
        ShiftMaster.objects.get_or_create(
            name=shift["name"],
            defaults={
                "start_time": shift["start_time"],
                "end_time": shift["end_time"],
                "is_night_shift": shift["is_night_shift"],
                "grace_period_minutes": shift["grace_period_minutes"],
                "is_default": shift["is_default"],
            },
        )


def remove_shifts(apps, schema_editor):
    ShiftMaster = apps.get_model('appEmp', 'ShiftMaster')
    ShiftMaster.objects.filter(name__in=[s["name"] for s in SHIFTS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('appEmp', '0046_empdocument_is_rejected_empdocument_rejection_reason_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_shifts, remove_shifts),
    ]
