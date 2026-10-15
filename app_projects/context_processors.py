from appEmp.models import empProfile
from app_organizations.entitlements import modules_for_request

from .access import can_manage_projects, can_view_all_projects

def project_nav(request):
    """Sidebar flags for the Projects entry."""
    none = {"projects_nav_show": False, "projects_nav_all": False, "projects_nav_manage": False}
    user = getattr(request, "user", None)
    org = getattr(request, "current_org", None)
    if user is None or not user.is_authenticated or org is None:
        return none
    if "projects" not in modules_for_request(request):
        return none

    if can_view_all_projects(user, org):
        return {
            "projects_nav_show": True,
            "projects_nav_all": True,
            "projects_nav_manage": can_manage_projects(user, org),
        }

    has_project = empProfile.objects.filter(
        user=user, organization=org, is_active=True, project__isnull=False
    ).exists()
    return {
        "projects_nav_show": has_project,
        "projects_nav_all": False,
        "projects_nav_manage": can_manage_projects(user, org),
    }
