from decimal import Decimal

from django.db.models import Q


class StatutoryRuleMissing(Exception):
    """No rule was in force for the key on the requested date."""


def get_rule(key, on_date):
    """
    Return the Decimal value of the statutory rule `key` that was in force
    on `on_date`. Raises StatutoryRuleMissing if there is none.
    """
    from .models import StatutoryRule

    rule = (
        StatutoryRule.objects
        .filter(key=key, effective_from__lte=on_date)
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=on_date))
        .order_by('-effective_from')
        .first()
    )
    if rule is None:
        raise StatutoryRuleMissing(f"No {key} rule in force on {on_date}.")
    return Decimal(rule.value)
