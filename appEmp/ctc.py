"""
Salary structure for an offer where employer PF/ESI are INSIDE the CTC.

    CTC = gross pay + employer PF + employer ESI

HR gives the CTC, the Basic as a % of gross and the HRA as a % of Basic. Optional
fixed DA and other allowances can be given too. Special Allowance is whatever is
left of the gross. Gross pay is the stored source of truth after this: when a
ceiling or rate changes later, nobody's pay changes until HR revises the salary.

The employer PF depends on the statutory wages, which depend on the gross, which
depends on the employer PF. So the function tries every combination of
(ESI on/off) x (PF capped / Basic+DA / 50% rule) as a straight-line equation,
keeps the combinations whose own assumptions hold, and picks the highest gross.
"""
from decimal import ROUND_HALF_UP, Decimal

from .statutory import get_rule

CENT = Decimal("0.01")
ZERO = Decimal("0")


class CtcStructureError(ValueError):
    """The CTC cannot be split with the percentages given."""


def _m(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def solve_ctc_structure(
    ctc, basic_pct, hra_pct, on_date, da=0, other_allowances=0,
    pf_applicable=True, esi_applicable=True, pf_on_full_wage=False,
):
    """
    ctc            monthly CTC (Decimal or number)
    basic_pct      Basic as a percentage of gross, e.g. 50
    hra_pct        HRA as a percentage of Basic, e.g. 40
    on_date        date whose statutory rules apply (PF ceiling, rates)
    Returns a dict: gross, basic, hra, da, special_allowance, other_allowances,
    statutory_wages, employer_pf, employer_esi, ctc_check, difference, warnings.
    """
    ctc = Decimal(str(ctc))
    bp = Decimal(str(basic_pct)) / 100
    hp = Decimal(str(hra_pct)) / 100
    d = Decimal(str(da))
    o = Decimal(str(other_allowances))
    if ctc <= ZERO:
        raise CtcStructureError("CTC must be greater than zero.")
    if not (ZERO < bp <= 1):
        raise CtcStructureError("Basic % must be between 0 and 100.")
    if hp < ZERO:
        raise CtcStructureError("HRA % cannot be negative.")

    ceiling = get_rule("EPF_WAGE_CEILING", on_date)
    share = get_rule("WAGES_MIN_SHARE", on_date)
    pf_rate = (
        get_rule("EPF_EMPLOYER_EPS_RATE", on_date)
        + get_rule("EPF_EMPLOYER_EPF_RATE", on_date)
        + get_rule("EDLI_RATE", on_date)
        + get_rule("EPF_ADMIN_RATE", on_date)
    )
    esic_ceiling = get_rule("ESIC_WAGE_CEILING", on_date)
    esic_rate = get_rule("ESIC_EMPLOYER_RATE", on_date)
    er = pf_rate if pf_applicable else ZERO

    candidates = []
    for esi_on in ((False, True) if esi_applicable else (False,)):
        ef = esic_rate if esi_on else ZERO
        pf_cases = []
        if not pf_applicable:
            pf_cases.append(("none", ZERO, ZERO))
        else:
            if not pf_on_full_wage:
                pf_cases.append(("cap", ceiling, ZERO))
            pf_cases.append(("basic_da", d, bp))
            pf_cases.append(("share", ZERO, share))
        for name, const, coef in pf_cases:
            gross = (ctc - er * const) / (1 + ef + er * coef)
            if gross <= ZERO:
                continue
            basic_da = bp * gross + d
            floor = share * gross
            wages = max(basic_da, floor)
            if name == "cap":
                ok_pf = wages >= ceiling
            elif name == "basic_da":
                ok_pf = basic_da >= floor and (pf_on_full_wage or basic_da <= ceiling)
            elif name == "share":
                ok_pf = floor >= basic_da and (pf_on_full_wage or floor <= ceiling)
            else:
                ok_pf = True
            if esi_applicable:
                ok_esi = gross <= esic_ceiling if esi_on else gross > esic_ceiling
            else:
                ok_esi = True
            if ok_pf and ok_esi:
                candidates.append((gross, esi_on))

    if not candidates:
        raise CtcStructureError(
            "This CTC cannot be split with these percentages. Try a different Basic %."
        )
    gross, esi_on = max(candidates)

    gross = _m(gross)
    basic = _m(bp * gross)
    hra = _m(hp * basic)
    da_amt = _m(d)
    other = _m(o)
    special = gross - basic - hra - da_amt - other
    if special < ZERO:
        raise CtcStructureError(
            "Basic, HRA, DA and allowances add up to more than the gross "
            f"({gross:,.2f}). Lower the percentages or the fixed allowances."
        )

    wages = max(basic + da_amt, _m(gross * share))
    warnings = []
    if basic + da_amt < _m(gross * share):
        warnings.append(
            f"Basic + DA is below {share * 100:.0f}% of gross, so PF will be "
            f"calculated on {share * 100:.0f}% of pay (the wages rule)."
        )

    employer_pf = ZERO
    if pf_applicable:
        base = wages if pf_on_full_wage else min(wages, ceiling)
        employer_pf = sum(
            (_m(base * get_rule(key, on_date))
             for key in ("EPF_EMPLOYER_EPS_RATE", "EPF_EMPLOYER_EPF_RATE",
                         "EDLI_RATE", "EPF_ADMIN_RATE")),
            ZERO,
        )
    employer_esi = _m(gross * esic_rate) if esi_on else ZERO
    ctc_check = gross + employer_pf + employer_esi
    return {
        "gross": gross, "basic": basic, "hra": hra, "da": da_amt,
        "special_allowance": special, "other_allowances": other,
        "statutory_wages": wages, "employer_pf": employer_pf,
        "employer_esi": employer_esi, "ctc_check": ctc_check,
        "difference": ctc - ctc_check, "warnings": warnings,
    }
