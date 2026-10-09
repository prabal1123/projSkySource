"""
Re-encrypt every stored encrypted value with the newest key.

Rotation steps:
1. Generate a new key and put it FIRST in FIELD_ENCRYPTION_KEYS, keeping the
   old keys after it. Restart the app.
2. Take a database backup.
3. python manage.py rotate_encryption_keys --dry-run
4. python manage.py rotate_encryption_keys
5. Keep the old key stored safely for as long as any backup made with it
   may need restoring.

Only counts are printed, never values or keys. BLIND_INDEX_KEY is separate
and is not affected by rotation.
"""
from cryptography.fernet import Fernet, InvalidToken
from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from appEmp.fields import ENCRYPTED_PREFIX, _EncryptedTextBase, _get_cipher

BATCH = 500


def _encrypted_fields():
    seen = set()
    found = []
    for model in apps.get_models():
        for field in model._meta.concrete_fields:
            if isinstance(field, _EncryptedTextBase):
                key = (field.model, field.name)
                if key not in seen:
                    seen.add(key)
                    found.append(field)
    return found


def _rows(field):
    """Yield (pk, stored_text) for every non-empty stored value, in batches."""
    quote = connection.ops.quote_name
    table = quote(field.model._meta.db_table)
    pk_col = quote(field.model._meta.pk.column)
    col = quote(field.column)
    last = None
    while True:
        sql = "SELECT %s, %s FROM %s WHERE %s IS NOT NULL AND %s <> ''" % (
            pk_col, col, table, col, col,
        )
        params = []
        if last is not None:
            sql += " AND %s > %%s" % pk_col
            params.append(last)
        sql += " ORDER BY %s LIMIT %d" % (pk_col, BATCH)
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            batch = cursor.fetchall()
        if not batch:
            return
        for pk, stored in batch:
            yield pk, stored
        last = batch[-1][0]


def _token(label, pk, stored):
    if not stored.startswith(ENCRYPTED_PREFIX):
        raise CommandError(
            "%s (id %s) is not in the expected encrypted format. Nothing was changed."
            % (label, pk)
        )
    return stored[len(ENCRYPTED_PREFIX):].encode("ascii")


class Command(BaseCommand):
    help = (
        "Re-encrypt all encrypted fields with the newest key in "
        "FIELD_ENCRYPTION_KEYS. Take a database backup first. "
        "Use --dry-run to count without writing."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="Count what would change, write nothing."
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        keys = list(getattr(settings, "FIELD_ENCRYPTION_KEYS", None) or [])
        if not keys:
            raise CommandError("FIELD_ENCRYPTION_KEYS is not set.")
        if len(keys) == 1:
            self.stdout.write(
                "Only one key is configured. To rotate, put the new key first and keep the old one after it."
            )

        primary = Fernet(keys[0].encode())
        cipher = _get_cipher()
        fields = _encrypted_fields()
        if not fields:
            self.stdout.write("No encrypted fields found.")
            return

        quote = connection.ops.quote_name
        total = already = rotated = skipped = 0

        with transaction.atomic():
            for field in fields:
                label = "%s.%s" % (field.model._meta.label, field.name)
                table = quote(field.model._meta.db_table)
                pk_col = quote(field.model._meta.pk.column)
                col = quote(field.column)
                f_total = f_already = f_rotated = f_skipped = 0

                for pk, stored in _rows(field):
                    f_total += 1
                    token = _token(label, pk, stored)
                    try:
                        primary.decrypt(token)
                        f_already += 1
                        continue
                    except InvalidToken:
                        pass
                    try:
                        new_token = cipher.rotate(token)
                    except InvalidToken:
                        raise CommandError(
                            "%s (id %s) cannot be decrypted with any configured key. "
                            "Nothing was changed." % (label, pk)
                        ) from None
                    f_rotated += 1
                    if not dry_run:
                        with connection.cursor() as cursor:
                            cursor.execute(
                                "UPDATE %s SET %s = %%s WHERE %s = %%s AND %s = %%s"
                                % (table, col, pk_col, col),
                                [ENCRYPTED_PREFIX + new_token.decode("ascii"), pk, stored],
                            )
                            if cursor.rowcount == 0:
                                f_rotated -= 1
                                f_skipped += 1

                self.stdout.write(
                    "%s: %d values, %d already on newest key, %d %s, %d changed during the run"
                    % (label, f_total, f_already, f_rotated,
                       "would rotate" if dry_run else "rotated", f_skipped)
                )
                total += f_total
                already += f_already
                rotated += f_rotated
                skipped += f_skipped

            if not dry_run:
                for field in fields:
                    label = "%s.%s" % (field.model._meta.label, field.name)
                    for pk, stored in _rows(field):
                        try:
                            primary.decrypt(_token(label, pk, stored))
                        except InvalidToken:
                            raise CommandError(
                                "Final check failed: %s (id %s) is not on the newest key. "
                                "Everything was rolled back." % (label, pk)
                            ) from None

        self.stdout.write(
            "%sTOTAL values=%d already=%d rotated=%d skipped_changed=%d"
            % ("DRY RUN " if dry_run else "", total, already, rotated, skipped)
        )
