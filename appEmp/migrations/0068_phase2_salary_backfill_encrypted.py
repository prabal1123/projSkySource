"""
Phase 2 salary encryption, step 2: copy salary figures into the encrypted columns.

- Copies each plain value into its *_enc column and nothing else.
- Safe to re-run: rows whose encrypted column already matches are skipped.
- Uses update() so updated_at and save() logic are not touched.
- Verifies every value at the end by reading it back and comparing it with the
  original, and checks the stored text is ciphertext. Any difference rolls the
  whole migration back.
- Only counts are printed, never amounts.
"""
from django.db import connection, migrations

BATCH_SIZE = 500

TARGETS = (
    (
        "Salary",
        (
            ("basic_salary", "basic_salary_enc"),
            ("hra", "hra_enc"),
            ("pf", "pf_enc"),
            ("daily_rate", "daily_rate_enc"),
        ),
    ),
    ("WageRegisterEntry", (("rate_override", "rate_override_enc"),)),
)


def _wanted(row, pairs):
    return {new: getattr(row, old) for old, new in pairs}


def _backfill_model(apps, model_name, pairs):
    Model = apps.get_model("appEmp", model_name)
    pks = list(Model.objects.order_by("pk").values_list("pk", flat=True))
    updated = 0
    skipped = 0
    for start in range(0, len(pks), BATCH_SIZE):
        chunk = pks[start:start + BATCH_SIZE]
        for row in Model.objects.filter(pk__in=chunk).order_by("pk"):
            wanted = _wanted(row, pairs)
            if all(getattr(row, name) == value for name, value in wanted.items()):
                skipped += 1
                continue
            Model.objects.filter(pk=row.pk).update(**wanted)
            updated += 1
    return Model, len(pks), updated, skipped


def _verify(Model, pairs, expected):
    count = 0
    bad = []
    for row in Model.objects.order_by("pk").iterator():
        count += 1
        for name, value in _wanted(row, pairs).items():
            if getattr(row, name) != value:
                bad.append("%s id %s field %s" % (Model.__name__, row.pk, name))
    if count != expected:
        raise RuntimeError("Backfill verification failed: the row count changed.")
    if bad:
        raise RuntimeError("Backfill verification failed for: " + ", ".join(bad))

    table = Model._meta.db_table
    unmarked = []
    with connection.cursor() as cursor:
        for _old, new in pairs:
            cursor.execute(
                'SELECT COUNT(*) FROM "%s" WHERE "%s" IS NOT NULL '
                "AND \"%s\" <> '' AND \"%s\" NOT LIKE 'enc1:%%'" % (table, new, new, new)
            )
            if cursor.fetchone()[0]:
                unmarked.append(new)
    if unmarked:
        raise RuntimeError(
            "Backfill verification failed: unencrypted values in " + ", ".join(unmarked)
        )


def backfill(apps, schema_editor):
    for model_name, pairs in TARGETS:
        Model, total, updated, skipped = _backfill_model(apps, model_name, pairs)
        _verify(Model, pairs, total)
        print(
            "\n  %s: %d updated, %d already done, %d total"
            % (model_name, updated, skipped, total)
        )


class Migration(migrations.Migration):

    dependencies = [
        ("appEmp", "0067_phase2_salary_add_encrypted_columns"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
