from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from .models import OrganizationMember

ALL_ROLES = ("owner", "admin", "manager", "member")


def get_user_membership(user):
    """The user's single OrganizationMember row, or None."""
    return (
        OrganizationMember.objects
        .select_related("organization")
        .filter(user=user)
        .first()
    )


def require_org_role(allowed_roles=None):
    """
    Allow the view only for users whose role in their own org is in
    allowed_roles (default: any role).

    - Anonymous users are sent to the login page.
    - Superusers always pass.
    - Everyone else must have request.current_org (set by the
      middleware) and a membership in that same org, with an allowed role.
    - Sets request.org_membership. Never changes request.current_org.
    """
    if allowed_roles is None:
        allowed_roles = ALL_ROLES

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path())

            membership = get_user_membership(user)

            if user.is_superuser:
                request.org_membership = membership
                return view_func(request, *args, **kwargs)

            org = getattr(request, "current_org", None)
            if (
                org is None
                or membership is None
                or membership.organization_id != org.id
                or membership.role not in allowed_roles
            ):
                raise PermissionDenied(
                    "You do not have permission to access this organization."
                )

            request.org_membership = membership
            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator
