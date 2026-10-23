"""
Professional tax (Payroll Phase 4a).

Professional tax is a state levy on monthly pay. The slabs are data in the
ProfessionalTaxSlab table (edited by superusers in Django admin), never
hardcoded here. Slab figures are only as good as the rows entered, so every
seeded row carries a "verify with CA" note.

Slab rules
----------
* A slab matches when  above < pay <= up_to  (up_to blank = no upper limit).
* gender "A" slabs apply to everyone. If a state has any "M" or "F" slabs it
  is treated as different for men and women and the employee's gender must be
  set; otherwise professional tax is taken as zero with a warning.
* month blank = every month. A month-specific slab (for example February)
  wins over an every-month slab whenever both match the pay.
* pay is the EARNED pay of the month (open question for the CA).
"""
import re
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0")
CENT = Decimal("0.01")

INDIAN_STATES = (
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim",
    "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
    "West Bengal",
    "Andaman and Nicobar Islands", "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir",
    "Ladakh", "Lakshadweep", "Puducherry",
)


def state_key(name):
    """Case-, space- and punctuation-insensitive key for matching state names."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _d(value):
    return Decimal(str(value))


def _money(value):
    return _d(value).quantize(CENT, rounding=ROUND_HALF_UP)


def professional_tax(slabs, gender, gross, month):
    """
    Professional tax for one month.

    slabs   the slabs of ONE state that are in force for the month
    gender  "M", "F" or blank
    gross   earned pay of the month
    month   calendar month, 1-12

    Returns (amount, warning). warning is "" when there is nothing to report.
    """
    gross = _d(gross or 0)
    if gross <= ZERO:
        return ZERO, ""
    slabs = list(slabs)
    if not slabs:
        return ZERO, "No professional tax slabs were found; professional tax was taken as zero."

    gender = (gender or "").strip().upper()
    if any(s.gender != "A" for s in slabs):
        if gender not in ("M", "F"):
            return ZERO, (
                "This state has different professional tax slabs for men and women, "
                "but the employee's gender is not set. Professional tax was taken as "
                "zero. Set the gender in the employee's PF and ESI settings."
            )
        pool = [s for s in slabs if s.gender == gender] or [s for s in slabs if s.gender == "A"]
    else:
        pool = slabs

    matching = [
        s for s in pool
        if _d(s.above) < gross
        and (s.up_to is None or gross <= _d(s.up_to))
        and (s.month is None or s.month == month)
    ]
    if not matching:
        return ZERO, (
            f"No professional tax slab matches earned pay of Rs {gross:,.2f}; "
            "professional tax was taken as zero."
        )

    candidates = [s for s in matching if s.month is not None] or matching
    chosen = max(candidates, key=lambda s: _d(s.above))
    warning = ""
    if len(candidates) > 1:
        warning = (
            "More than one professional tax slab matches this pay (the slab ranges "
            f"overlap); the slab starting above Rs {_d(chosen.above):,.2f} was used."
        )
    return _money(chosen.amount), warning
