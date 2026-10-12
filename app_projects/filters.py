import uuid as uuid_lib

from .access import can_manage_projects
from .models import Project

FILTER_UNASSIGNED = "unassigned"


def can_use_project_filter(user, org):
    """Who sees the project dropdown. Admin-level only for now."""
    return can_manage_projects(user, org)


def clean_project_filter(org, raw):
    """Return "", "unassigned", or the uuid string of a project in this org."""
    raw = (raw or "").strip()
    if raw == FILTER_UNASSIGNED:
        return raw
    try:
        parsed = uuid_lib.UUID(raw)
    except (ValueError, TypeError, AttributeError):
        return ""
    if Project.objects.filter(organization=org, uuid=parsed).exists():
        return str(parsed)
    return ""


def apply_project_filter(queryset, selected, path="project"):
    """Narrow a queryset by project. path is the field path to the project."""
    if selected == FILTER_UNASSIGNED:
        return queryset.filter(**{path + "__isnull": True})
    if selected:
        return queryset.filter(**{path + "__uuid": selected})
    return queryset


def project_filter_context(request):
    """Template context for the dropdown, empty for users who may not use it."""
    org = getattr(request, "current_org", None)
    user = getattr(request, "user", None)
    if org is None or user is None or not can_use_project_filter(user, org):
        return {
            "project_filter_show": False,
            "project_filter_selected": "",
            "project_filter_options": [],
        }
    options = []
    for project in Project.objects.filter(organization=org).order_by("name"):
        label = project.name
        if project.status == Project.STATUS_ARCHIVED:
            label += " (archived)"
        options.append({"uuid": str(project.uuid), "label": label})
    return {
        "project_filter_show": True,
        "project_filter_selected": clean_project_filter(org, request.GET.get("project")),
        "project_filter_options": options,
    }
