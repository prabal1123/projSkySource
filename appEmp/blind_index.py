"""
Blind-index helper (Phase 2, step 2.4).

A blind index is a keyed fingerprint of a value (HMAC-SHA256 with
settings.BLIND_INDEX_KEY, a secret separate from the encryption keys). The
same normalised value always gives the same fingerprint, so the database can
check equality and uniqueness without decrypting anything.

Rules:
- The value is cleaned first, so different ways of writing the same number
  give the same fingerprint.
- A label for the field kind is mixed in, so the same digits in two different
  kinds never share a fingerprint.
- Empty values give None (stored as NULL, so a unique rule ignores them).
- Error messages and logs never contain a value or a key.
- Changing BLIND_INDEX_KEY changes every fingerprint. It is a long-lived secret.
"""
import hashlib
import hmac
import re

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

KIND_AADHAAR = "aadhaar"
KIND_PHONE = "phone"

AADHAAR_DIGITS = 12
PHONE_MATCH_DIGITS = 10

_AADHAAR_ALLOWED = re.compile(r"[\d\s\-]+")
_NON_DIGITS = re.compile(r"\D")


class BlindIndexError(ValueError):
    """A value cannot be fingerprinted. The message never contains the value."""


def _normalize_aadhaar(value):
    text = str(value).strip()
    if not text:
        return None
    if not _AADHAAR_ALLOWED.fullmatch(text):
        raise BlindIndexError("Aadhaar must contain only digits, spaces or dashes.")
    digits = _NON_DIGITS.sub("", text)
    if len(digits) != AADHAAR_DIGITS:
        raise BlindIndexError("Aadhaar must be exactly 12 digits.")
    return digits


def _normalize_phone(value):
    digits = _NON_DIGITS.sub("", str(value))
    if len(digits) < PHONE_MATCH_DIGITS:
        return None
    return digits[-PHONE_MATCH_DIGITS:]


_NORMALIZERS = {
    KIND_AADHAAR: _normalize_aadhaar,
    KIND_PHONE: _normalize_phone,
}


def _get_key():
    key = (getattr(settings, "BLIND_INDEX_KEY", "") or "").strip()
    if len(key) < 32:
        raise ImproperlyConfigured("BLIND_INDEX_KEY is missing or shorter than 32 characters.")
    return key.encode("utf-8")


def blind_index(kind, value):
    """Return the 64-character hex fingerprint of value, or None if it is empty."""
    try:
        normalize = _NORMALIZERS[kind]
    except KeyError:
        raise ValueError("Unsupported blind-index kind.") from None
    if value is None:
        return None
    normalized = normalize(value)
    if not normalized:
        return None
    message = (kind + ":" + normalized).encode("utf-8")
    return hmac.new(_get_key(), message, hashlib.sha256).hexdigest()


def aadhaar_index(value):
    return blind_index(KIND_AADHAAR, value)


def phone_index(value):
    return blind_index(KIND_PHONE, value)


def indexes_equal(first, second):
    """Constant-time comparison. Two missing fingerprints are never equal."""
    if not first or not second:
        return False
    return hmac.compare_digest(first, second)
