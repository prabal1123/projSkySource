from django.db import migrations


def backfill(apps, schema_editor):
    Salary = apps.get_model("appEmp", "Salary")
    WageRegisterEntry = apps.get_model("appEmp", "WageRegisterEntry")
    BCASPass = apps.get_model("appEmp", "BCASPass")

    for s in Salary.objects.filter(organization__isnull=True).select_related("employee"):
        s.organization_id = s.employee.organization_id
        s.save(update_fields=["organization"])

    for w in WageRegisterEntry.objects.filter(organization__isnull=True).select_related("salary"):
        w.organization_id = w.salary.organization_id
        w.save(update_fields=["organization"])

    for b in BCASPass.objects.filter(organization__isnull=True).select_related("employee"):
        b.organization_id = b.employee.organization_id
        b.save(update_fields=["organization"])


class Migration(migrations.Migration):

    dependencies = [
        ("appEmp", "0061_org_on_salary_wage_bcas_nullable"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
