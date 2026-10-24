"""
Income tax on salary, TDS (Payroll Phase 5a).

TDS is projected for the whole financial year (April to March) and spread over
the months that are left:

  projected pay  = pay of earlier months of the year + this month's earned pay
                   + full monthly gross for each month still to come
  taxable income = projected pay - standard deduction
                   (old regime: also minus the declared deductions)
  tax            = slab tax, less the rebate (new regime has marginal relief
                   just above the rebate limit), plus cess
  this month     = (tax for the year - TDS already deducted) / months left

Slabs are IncomeTaxSlab rows; standard deduction, rebate and cess are
StatutoryRule keys starting with TAX_. Nothing is hardcoded here, and every
seeded row carries a "verify with CA" note.

Not handled yet (a warning or a note says so): surcharge, senior-citizen slabs
of the old regime, income from a previous employer, and the detailed breakup
of old-regime deductions (a single yearly figure is used instead).
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q
from django.utils import timezone

ZERO = Decimal("0")
CENT = Decimal("0.01")
REGIME_NEW = "NEW"
REGIME_OLD = "OLD"

PARAM_KEYS = (
    "TAX_STD_DEDUCTION_NEW",
    "TAX_STD_DEDUCTION_OLD",
    "TAX_REBATE_LIMIT_NEW",
    "TAX_REBATE_MAX_NEW",
    "TAX_REBATE_LIMIT_OLD",
    "TAX_REBATE_MAX_OLD",
    "TAX_CESS_RATE",
    "TAX_SURCHARGE_FROM",
)


class TaxRulesMissing(Exception):
    """Income tax slabs or parameters are not set up for the requested date."""


def _money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def fy_start_year(year, month):
    """Calendar year in which the financial year of this month started."""
    return year if month >= 4 else year - 1


def months_left_in_fy(month):
    """Months from this month to March, this month included."""
    return 16 - month if month >= 4 else 4 - month


@dataclass
class TaxRules:
    slabs: dict
    params: dict


@dataclass
class TdsResult:
    taxable_income: Decimal = ZERO
    annual_tax: Decimal = ZERO
    monthly: Decimal = ZERO
    warnings: list = field(default_factory=list)


def load_tax_rules(on_date):
    """Slabs and parameters in force on a date (two queries). Raises TaxRulesMissing."""
    from .models import IncomeTaxSlab, StatutoryRule

    slabs = {REGIME_NEW: [], REGIME_OLD: []}
    rows = IncomeTaxSlab.objects.filter(effective_from__lte=on_date).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gte=on_date)
    )
    for s in rows:
        slabs.setdefault(s.regime, []).append((
            Decimal(s.above),
            None if s.up_to is None else Decimal(s.up_to),
            Decimal(s.rate),
        ))
    for regime in slabs:
        slabs[regime].sort(key=lambda r: r[0])

    params = {}
    rules = (
        StatutoryRule.objects.filter(key__in=PARAM_KEYS, effective_from__lte=on_date)
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=on_date))
        .order_by("effective_from")
    )
    for r in rules:
        params[r.key] = Decimal(r.value)

    missing = [k for k in PARAM_KEYS if k not in params]
    if missing:
        raise TaxRulesMissing("missing rules: " + ", ".join(missing))
    if not slabs[REGIME_NEW] or not slabs[REGIME_OLD]:
        raise TaxRulesMissing("income tax slabs are missing")
    return TaxRules(slabs=slabs, params=params)


def annual_tax(rules, regime, taxable):
    """Tax for the year on a taxable income, after rebate, with cess."""
    taxable = max(Decimal(taxable), ZERO)
    tax = ZERO
    for above, up_to, rate in rules.slabs[regime]:
        if taxable > above:
            top = taxable if up_to is None else min(taxable, up_to)
            tax += (top - above) * rate
    p = rules.params
    if regime == REGIME_OLD:
        limit, cap = p["TAX_REBATE_LIMIT_OLD"], p["TAX_REBATE_MAX_OLD"]
    else:
        limit, cap = p["TAX_REBATE_LIMIT_NEW"], p["TAX_REBATE_MAX_NEW"]
    if taxable <= limit:
        tax -= min(tax, cap)
    elif regime == REGIME_NEW:
        # Marginal relief: just above the limit, tax never exceeds the excess.
        tax = min(tax, taxable - limit)
    tax += tax * p["TAX_CESS_RATE"]
    return _money(tax)


def compute_tds(rules, regime, projected_gross, declared_deductions, tds_deducted, months_left):
    """TDS for one month from the projected pay of the whole year."""
    regime = REGIME_OLD if regime == REGIME_OLD else REGIME_NEW
    p = rules.params
    if regime == REGIME_OLD:
        deductions = p["TAX_STD_DEDUCTION_OLD"] + Decimal(declared_deductions or 0)
    else:
        deductions = p["TAX_STD_DEDUCTION_NEW"]
    taxable = max(ZERO, Decimal(projected_gross) - deductions)
    tax = annual_tax(rules, regime, taxable)
    months_left = max(int(months_left), 1)
    monthly = _money(max(ZERO, (tax - Decimal(tds_deducted)) / Decimal(months_left)))
    warnings = []
    if taxable > p["TAX_SURCHARGE_FROM"]:
        warnings.append(
            "Projected taxable income is above the surcharge limit; surcharge is not "
            "included in TDS. Check with the CA."
        )
    return TdsResult(taxable_income=taxable, annual_tax=tax, monthly=monthly, warnings=warnings)


def estimate_monthly_tds(salary, on_date=None):
    """
    Estimate for the salary screens: a full year of this salary, nothing
    deducted yet. Zero when TDS is off for the employee or rules are missing.
    """
    from .models import EmployeeStatutoryProfile

    profile = EmployeeStatutoryProfile.objects.filter(employee_id=salary.employee_id).first()
    if profile is not None and profile.tds_mode == "NA":
        return ZERO
    regime = profile.tax_regime if profile is not None else REGIME_NEW
    declared = profile.declared_deductions if profile is not None else ZERO
    try:
        rules = load_tax_rules(on_date or timezone.localdate())
    except TaxRulesMissing:
        return ZERO
    out = compute_tds(rules, regime, salary.gross_monthly * 12, declared, ZERO, 12)
    return out.monthly
