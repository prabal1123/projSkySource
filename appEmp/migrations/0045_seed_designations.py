from django.db import migrations


DESIGNATIONS = [
    "Supervisor",
    "Bird Chaser",
    "Sr. Supervisor",
]


def seed_designations(apps, schema_editor):
    DesignationMaster = apps.get_model('appEmp', 'DesignationMaster')
    for name in DESIGNATIONS:
        DesignationMaster.objects.get_or_create(name=name)


def remove_designations(apps, schema_editor):
    DesignationMaster = apps.get_model('appEmp', 'DesignationMaster')
    DesignationMaster.objects.filter(name__in=DESIGNATIONS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('appEmp', '0044_whatsappotp'),
    ]

    operations = [
        migrations.RunPython(seed_designations, remove_designations),
    ]
