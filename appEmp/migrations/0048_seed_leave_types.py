from django.db import migrations


LEAVE_TYPES = [
    {
        "name": "Casual Leave",
        "code": "CL",
        "is_paid": True,
        "allow_half_day": True,
        "requires_document": False,
    },
    {
        "name": "Sick Leave",
        "code": "SL",
        "is_paid": True,
        "allow_half_day": True,
        "requires_document": True,
    },
    {
        "name": "Earned Leave",
        "code": "EL",
        "is_paid": True,
        "allow_half_day": True,
        "requires_document": False,
    },
    {
        "name": "Loss of Pay",
        "code": "LOP",
        "is_paid": False,
        "allow_half_day": False,
        "requires_document": False,
    },
]


def seed_leave_types(apps, schema_editor):
    LeaveTypeMaster = apps.get_model('appEmp', 'LeaveTypeMaster')
    for lt in LEAVE_TYPES:
        LeaveTypeMaster.objects.get_or_create(
            name=lt["name"],
            defaults={
                "code": lt["code"],
                "is_paid": lt["is_paid"],
                "allow_half_day": lt["allow_half_day"],
                "requires_document": lt["requires_document"],
            },
        )


def remove_leave_types(apps, schema_editor):
    LeaveTypeMaster = apps.get_model('appEmp', 'LeaveTypeMaster')
    LeaveTypeMaster.objects.filter(name__in=[lt["name"] for lt in LEAVE_TYPES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('appEmp', '0047_seed_shifts'),
    ]

    operations = [
        migrations.RunPython(seed_leave_types, remove_leave_types),
    ]
