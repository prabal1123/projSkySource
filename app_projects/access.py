"""
Who may see and manage projects.

Rules (the same as Lite):
- Owner, admin and manager see every project in the current organization
  and may create, edit and archive them.
- Anyone else sees only the project on their own employee profile.
- A superuser sees every project of the organization they are working in.

The same abilities can also be granted through the Django permissions
view_all_projects and manage_projects (for example to a new role's group).
A permission only counts inside the user's own organization.
"""

from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404

from app_organizations.models import OrganizationMember
from appEmp.models import empProfile

from .models import Project

VIEW_ALL_ROLES = ("owner", "admin", "manager")
MANAGE_ROLES = ("owner", "admin", "manager")


def _role_in(user, org):
    if org is None or not getattr(user, "is_authenticated", False):
        return None
    return (
        OrganizationMember.objects
        .filter(user=user, organization=org)
        .values_list("role", flat=True)
        .first()
    )


def _allowed(user, org, roles, codename):
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return org is not None
    role = _role_in(user, org)
    if role is None:
        return False
    return role in roles or user.has_perm("app_projects." + codename)


def can_view_all_projects(user, org):
    return _allowed(user, org, VIEW_ALL_ROLES, "view_all_projects")


def can_manage_projects(user, org):
    return _allowed(user, org, MANAGE_ROLES, "manage_projects")


def visible_projects(request):
    """Projects the current user may see inside request.current_org."""
    org = getattr(request, "current_org", None)
    user = getattr(request, "user", None)
    if org is None or user is None or not user.is_authenticated:
        return Project.objects.none()

    projects = Project.objects.filter(organization=org)
    if can_view_all_projects(user, org):
        return projects

    project_id = (
        empProfile.objects
        .filter(user=user, organization=org, is_active=True)
        .values_list("project_id", flat=True)
        .first()
    )
    if project_id:
        return projects.filter(pk=project_id)
    return projects.none()


def get_visible_project_or_404(request, project_uuid):
    """A project the user cannot see is a 404, so its existence is not revealed."""
    try:
        return get_object_or_404(visible_projects(request), uuid=project_uuid)
    except (ValueError, ValidationError):
        raise Http404("No project matches the given query.")
