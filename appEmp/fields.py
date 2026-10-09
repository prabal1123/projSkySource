"""
Encrypted model fields (Phase 2, step 2.3).

Values are encrypted with MultiFernet before they reach the database and
decrypted when read back. The first key in settings.FIELD_ENCRYPTION_KEYS
encrypts; every listed key can decrypt (this is what makes rotation possible).

Rules:
- None stays None and "" stays "" (neither is encrypted).
- Stored text always starts with ENCRYPTED_PREFIX. A stored value without it
  is treated as corrupt, never as plain text.
- A value that cannot be decrypted raises FieldDecryptionError and is logged
  without any value or key. Nothing is silently blanked, so a failed read can
  never be saved back over real data.
- The database cannot search encrypted columns, so every lookup except
  isnull raises FieldError. Use a blind-index column for exact matches.
- Columns are text (ciphertext is longer than the plain value). max_length is
  enforced on forms only.
"""
import logging
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django import forms
from django.conf import settings
from django.core.exceptions import FieldError, ImproperlyConfigured, ValidationError
from django.db import models

logger = logging.getLogger(__name__)

ENCRYPTED_PREFIX = "enc1:"


class FieldDecryptionError(Exception):
    """A stored value could not be decrypted (wrong key or corrupted data)."""


@lru_cache(maxsize=8)
def _build_cipher(keys):
    return MultiFernet([Fernet(key.encode()) for key in keys])


def _get_cipher():
    keys = tuple(getattr(settings, "FIELD_ENCRYPTION_KEYS", None) or ())
    if not keys:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEYS is not set.")
    return _build_cipher(keys)


def encrypt_value(plain):
    token = _get_cipher().encrypt(plain.encode("utf-8"))
    return ENCRYPTED_PREFIX + token.decode("ascii")


def decrypt_value(stored):
    if not stored.startswith(ENCRYPTED_PREFIX):
        logger.error("A stored encrypted-field value is not in the expected format.")
        raise FieldDecryptionError(
            "A stored value is not in the expected encrypted format."
        )
    try:
        plain = _get_cipher().decrypt(
            stored[len(ENCRYPTED_PREFIX):].encode("ascii")
        )
    except (InvalidToken, UnicodeEncodeError):
        logger.error(
            "Could not decrypt a stored field value: wrong key or corrupted data."
        )
        raise FieldDecryptionError(
            "A stored value could not be decrypted (wrong key or corrupted data)."
        ) from None
    return plain.decode("utf-8")


class _EncryptedTextBase(models.TextField):
    def get_lookup(self, lookup_name):
        if lookup_name != "isnull":
            raise FieldError(
                "Cannot use the '%s' lookup on encrypted field '%s'. Encrypted "
                "values cannot be searched in the database. Use the blind-index "
                "(fingerprint) column for exact matches." % (lookup_name, self.name)
            )
        return super().get_lookup(lookup_name)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == "":
            return value
        return encrypt_value(value)

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        return decrypt_value(value)


class EncryptedCharField(_EncryptedTextBase):
    """Single-line encrypted text (PAN, Aadhaar, bank account, UAN, ESIC, phone)."""

    def formfield(self, **kwargs):
        defaults = {"widget": forms.TextInput, "max_length": self.max_length}
        if self.null:
            defaults["empty_value"] = None
        defaults.update(kwargs)
        return super(models.TextField, self).formfield(
            form_class=forms.CharField, **defaults
        )


class EncryptedTextField(_EncryptedTextBase):
    """Multi-line encrypted text (for example address)."""


class EncryptedDecimalField(_EncryptedTextBase):
    """Encrypted decimal (salary, PF, ESI, deductions)."""

    def __init__(self, *args, max_digits=None, decimal_places=None, **kwargs):
        self.max_digits = max_digits
        self.decimal_places = decimal_places
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.max_digits is not None:
            kwargs["max_digits"] = self.max_digits
        if self.decimal_places is not None:
            kwargs["decimal_places"] = self.decimal_places
        return name, path, args, kwargs

    def to_python(self, value):
        if value is None or value == "":
            return None
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except InvalidOperation:
            raise ValidationError("Enter a valid number.", code="invalid") from None

    def get_prep_value(self, value):
        value = self.to_python(value)
        if value is None:
            return None
        if self.decimal_places is not None:
            value = value.quantize(
                Decimal(1).scaleb(-self.decimal_places), rounding=ROUND_HALF_UP
            )
        return encrypt_value(str(value))

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return None
        plain = decrypt_value(value)
        try:
            return Decimal(plain)
        except InvalidOperation:
            logger.error("A decrypted field value is not a valid decimal.")
            raise FieldDecryptionError("A stored value is not a valid decimal.") from None

    def formfield(self, **kwargs):
        defaults = {
            "max_digits": self.max_digits,
            "decimal_places": self.decimal_places,
        }
        defaults.update(kwargs)
        return super(models.TextField, self).formfield(
            form_class=forms.DecimalField, **defaults
        )
