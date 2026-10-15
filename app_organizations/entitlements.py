from django.db.models import Q
from django.utils import timezone

from .models import OrganizationModule
from .modules import CORE, MODULES, effective_modules
from .models import OrganizationModule
from .modules import CORE, MODULES, effective_modules

def direct_module_keys(org):
    """Modules with their own enabled, unexpired row."""
    now = timezone.now()
    keys = (
        OrganizationModule.objects
        .filter(organization=org, is_enabled=True)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .values_list("module_key", flat=True)
    )
    return {k for k in keys if k in MODULES}


def org_modules(org):
    if org is None:
        return set()
    return effective_modules(direct_module_keys(org))


def org_has_module(org, key):
    if key == CORE:
        return True
    return key in org_modules(org)



def modules_for_request(request):
    """The current org's active modules, looked up once per request."""
    cached = getattr(request, "_org_modules", None)
    if cached is None:
        cached = org_modules(getattr(request, "current_org", None))
        request._org_modules = cached
    return cached



def grant_modules(org, keys=None, source="manual"):
    """Turn modules on for an org (all of them by default). Idempotent."""
    for key in (keys or MODULES):
        OrganizationModule.objects.update_or_create(
            organization=org,
            module_key=key,
            defaults={"is_enabled": True, "expires_at": None, "source": source},
        )