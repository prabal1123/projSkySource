from appEmp.models import empProfile

from .access import can_view_all_projects


def project_nav(request):
    """Sidebar flags for the Projects entry."""
    none = {"projects_nav_show": False, "projects_nav_all": False}
    user = getattr(request, "user", None)
    org = getattr(request, "current_org", None)
    if user is None or not user.is_authenticated or org is None:
        return none

    if can_view_all_projects(user, org):
        return {"projects_nav_show": True, "projects_nav_all": True}

    has_project = empProfile.objects.filter(
        user=user, organization=org, is_active=True, project__isnull=False
    ).exists()
    return {"projects_nav_show": has_project, "projects_nav_all": False}
