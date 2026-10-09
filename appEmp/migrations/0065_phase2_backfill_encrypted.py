"""
Phase 2, step 2.5a: backfill the encrypted shadow columns and fingerprints.

- Validates every Aadhaar first. Malformed or colliding numbers stop the
  migration and are reported by profile id only (never by value).
- Copies each plain value into its *_enc column exactly as it is, and fills
  the aadhar_bidx / phone_bidx fingerprints.
- Safe to re-run: rows whose new columns already match are skipped.
- Uses update() so updated_at and save() logic are not touched.
- Verifies everything at the end. Any failure rolls the whole thing back.
"""
from collections import defaultdict

from django.db import connection, migrations

from appEmp.blind_index import BlindIndexError, aadhaar_index, phone_index

BATCH_SIZE = 500

PAIRS = (
    ("aadhar_no", "aadhar_no_enc"),
    ("pan_no", "pan_no_enc"),
    ("bank_account_no", "bank_account_no_enc"),
    ("uan_no", "uan_no_enc"),
    ("esic_no", "esic_no_enc"),
    ("phone_number", "phone_number_enc"),
    ("address", "address_enc"),
)


def _wanted(row):
    values = {new: getattr(row, old) for old, new in PAIRS}
    values["aadhar_bidx"] = aadhaar_index(row.aadhar_no)
    values["phone_bidx"] = phone_index(row.phone_number)
    return values


def _check_aadhaar(Profile):
    malformed = []
    groups = defaultdict(list)
    rows = (
        Profile.objects.exclude(aadhar_no__isnull=True)
        .exclude(aadhar_no="")
        .values_list("pk", "aadhar_no")
    )
    for pk, value in rows:
        try:
            fingerprint = aadhaar_index(value)
        except BlindIndexError:
            malformed.append(pk)
            continue
        if fingerprint:
            groups[fingerprint].append(pk)
    collisions = [sorted(ids) for ids in groups.values() if len(ids) > 1]
    if malformed or collisions:
        raise RuntimeError(
            "Backfill stopped, nothing was written. Fix these rows and run again. "
            "Malformed Aadhaar, profile ids: %s. "
            "Aadhaar that collide after cleaning, profile id groups: %s."
            % (sorted(malformed), collisions)
        )


def _verify(Profile, expected):
    count = 0
    bad = []
    for row in Profile.objects.order_by("pk").iterator():
        count += 1
        for name, value in _wanted(row).items():
            if getattr(row, name) != value:
                bad.append("profile %s field %s" % (row.pk, name))
    if count != expected:
        raise RuntimeError("Backfill verification failed: the row count changed.")
    if bad:
        raise RuntimeError("Backfill verification failed for: " + ", ".join(bad))

    table = Profile._meta.db_table
    unmarked = []
    with connection.cursor() as cursor:
        for _old, new in PAIRS:
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
    Profile = apps.get_model("appEmp", "empProfile")
    _check_aadhaar(Profile)

    pks = list(Profile.objects.order_by("pk").values_list("pk", flat=True))
    updated = 0
    skipped = 0
    for start in range(0, len(pks), BATCH_SIZE):
        chunk = pks[start:start + BATCH_SIZE]
        for row in Profile.objects.filter(pk__in=chunk).order_by("pk"):
            wanted = _wanted(row)
            if all(getattr(row, name) == value for name, value in wanted.items()):
                skipped += 1
                continue
            Profile.objects.filter(pk=row.pk).update(**wanted)
            updated += 1

    _verify(Profile, len(pks))
    print("\n  backfill: %d updated, %d already done, %d total" % (updated, skipped, len(pks)))


class Migration(migrations.Migration):

    dependencies = [
        ("appEmp", "0064_phase2_add_encrypted_columns"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
