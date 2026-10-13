import uuid as uuid_lib
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .access import (
    can_manage_projects,
    can_view_all_projects,
    get_visible_project_or_404,
    visible_projects,
)
from .forms import ProjectForm
from appEmp.models import empProfile

from .models import Project
from .services import actions_needing_reassign


def _current_org(request):
    org = getattr(request, "current_org", None)
    if org is None:
        raise PermissionDenied("No organization is linked to your account.")
    return org


def _require_manage(request, org):
    if not can_manage_projects(request.user, org):
        raise PermissionDenied("You do not have permission to manage projects.")


def _save(form, org):
    project = form.save(commit=False)
    project.organization = org
    try:
        with transaction.atomic():
            project.save()
    except IntegrityError:
        form.add_error(None, "A project with this name or code already exists.")
        return None
    return project


@login_required
def project_list_view(request):
    org = _current_org(request)
    view_all = can_view_all_projects(request.user, org)
    search = request.GET.get("q", "").strip()
    show_archived = request.GET.get("show_archived") == "1"

    projects = (
        visible_projects(request)
        .select_related("lead__user")
        .annotate(team_count=Count("employees", filter=Q(employees__is_active=True)))
    )
    if view_all and not show_archived:
        projects = projects.exclude(status=Project.STATUS_ARCHIVED)
    if search:
        projects = projects.filter(Q(name__icontains=search) | Q(code__icontains=search))

    return render(request, "app_projects/list.html", {
        "projects": projects,
        "search_query": search,
        "show_archived": show_archived,
        "view_all": view_all,
        "can_manage": can_manage_projects(request.user, org),
    })


@login_required
def project_detail_view(request, uuid):
    org = _current_org(request)
    project = get_visible_project_or_404(request, uuid)
    team = (
        project.employees.filter(is_active=True)
        .select_related("user")
        .order_by("user__first_name", "user__last_name")
    )
    return render(request, "app_projects/detail.html", {
        "project": project,
        "team": team,
        "reassign_list": (
            list(actions_needing_reassign(project).select_related("assignee__user")[:10])
            if can_manage_projects(request.user, org) else []
        ),
        "can_manage": can_manage_projects(request.user, org),
    })


@login_required
def project_create_view(request):
    org = _current_org(request)
    _require_manage(request, org)

    if request.method == "POST":
        form = ProjectForm(request.POST, organization=org)
        if form.is_valid():
            project = _save(form, org)
            if project is not None:
                messages.success(request, "Project created.")
                return redirect("projectDetail", uuid=project.uuid)
    else:
        form = ProjectForm(organization=org)

    return render(request, "app_projects/form.html", {
        "form": form,
        "project": None,
        "page_title": "Add Project",
    })


@login_required
def project_edit_view(request, uuid):
    org = _current_org(request)
    project = get_visible_project_or_404(request, uuid)
    _require_manage(request, org)

    if project.is_archived:
        messages.error(request, "This project is archived. Unarchive it before editing.")
        return redirect("projectDetail", uuid=project.uuid)

    if request.method == "POST":
        form = ProjectForm(request.POST, instance=project, organization=org)
        if form.is_valid():
            saved = _save(form, org)
            if saved is not None:
                messages.success(request, "Project updated.")
                return redirect("projectDetail", uuid=saved.uuid)
    else:
        form = ProjectForm(instance=project, organization=org)

    return render(request, "app_projects/form.html", {
        "form": form,
        "project": project,
        "page_title": "Edit Project",
    })


@login_required
@require_POST
def project_archive_view(request, uuid):
    org = _current_org(request)
    project = get_visible_project_or_404(request, uuid)
    _require_manage(request, org)
    if not project.is_archived:
        project.archive()
        messages.success(request, "Project archived. It is now read-only.")
    return redirect("projectDetail", uuid=project.uuid)


@login_required
@require_POST
def project_unarchive_view(request, uuid):
    org = _current_org(request)
    project = get_visible_project_or_404(request, uuid)
    _require_manage(request, org)
    if project.is_archived:
        project.status = Project.STATUS_ACTIVE
        project.save(update_fields=["status", "updated_at"])
        messages.success(request, "Project unarchived.")
    return redirect("projectDetail", uuid=project.uuid)


ASSIGN_PAGE_SIZE = 50
ASSIGN_UNASSIGN = "none"
ASSIGN_FILTER_UNASSIGNED = "unassigned"


def _parse_uuid(value):
    try:
        return uuid_lib.UUID(str(value).strip())
    except (ValueError, TypeError):
        return None


def _assignable_projects(org):
    return (
        Project.objects.filter(organization=org)
        .exclude(status=Project.STATUS_ARCHIVED)
        .order_by("name")
    )


def _clean_project_filter(org, raw):
    raw = (raw or "").strip()
    if raw == ASSIGN_FILTER_UNASSIGNED:
        return raw
    parsed = _parse_uuid(raw)
    if parsed and Project.objects.filter(organization=org, uuid=parsed).exists():
        return str(parsed)
    return ""


def _assign_url(request):
    params = {}
    for key in ("q", "project", "page"):
        value = request.POST.get(key, "").strip()
        if value:
            params[key] = value
    url = reverse("projectAssign")
    if params:
        url += "?" + urlencode(params)
    return url


def _assign_apply(request, org):
    target_raw = request.POST.get("target", "").strip()
    if target_raw == ASSIGN_UNASSIGN:
        new_project = None
    else:
        parsed = _parse_uuid(target_raw)
        new_project = (
            _assignable_projects(org).filter(uuid=parsed).first() if parsed else None
        )
        if new_project is None:
            messages.error(
                request,
                "Choose a project that is active or on hold, or choose Unassigned.",
            )
            return

    selected = {value.strip() for value in request.POST.getlist("employees") if value.strip()}
    if not selected:
        messages.error(request, "Select at least one employee.")
        return

    valid = {parsed for parsed in (_parse_uuid(value) for value in selected) if parsed}
    employees = list(
        empProfile.objects
        .filter(organization=org, is_active=True, uuid__in=valid)
        .select_related("project")
    )
    skipped = len(selected) - len(employees)

    target_id = new_project.pk if new_project is not None else None
    counts = {"assigned": 0, "moved": 0, "unassigned": 0, "unchanged": 0}

    with transaction.atomic():
        for employee in employees:
            if employee.project_id == target_id:
                counts["unchanged"] += 1
                continue
            before = employee.project_id
            employee.project = new_project
            employee.save(update_fields=["project", "updated_at"])
            if new_project is None:
                counts["unassigned"] += 1
            elif before is None:
                counts["assigned"] += 1
            else:
                counts["moved"] += 1

    parts = []
    if counts["assigned"]:
        parts.append("%d assigned" % counts["assigned"])
    if counts["moved"]:
        parts.append("%d moved" % counts["moved"])
    if counts["unassigned"]:
        parts.append("%d unassigned" % counts["unassigned"])
    if counts["unchanged"]:
        parts.append("%d already in that project" % counts["unchanged"])

    changed = counts["assigned"] + counts["moved"] + counts["unassigned"]
    if changed:
        messages.success(request, "Done: " + ", ".join(parts) + ".")
    elif parts:
        messages.info(request, "No changes: " + ", ".join(parts) + ".")
    if skipped:
        messages.warning(request, "%d selected employee(s) could not be found and were skipped." % skipped)


@login_required
def project_assign_view(request):
    org = _current_org(request)
    _require_manage(request, org)

    if request.method == "POST":
        _assign_apply(request, org)
        return redirect(_assign_url(request))

    search = request.GET.get("q", "").strip()[:100]
    project_filter = _clean_project_filter(org, request.GET.get("project"))

    employees = (
        empProfile.objects
        .filter(organization=org, is_active=True)
        .select_related("user", "designation", "project")
        .order_by("user__first_name", "user__last_name", "pk")
    )
    for term in search.split():
        employees = employees.filter(
            Q(user__first_name__icontains=term)
            | Q(user__last_name__icontains=term)
            | Q(designation__name__icontains=term)
        )
    if project_filter == ASSIGN_FILTER_UNASSIGNED:
        employees = employees.filter(project__isnull=True)
    elif project_filter:
        employees = employees.filter(project__uuid=project_filter)

    page_obj = Paginator(employees, ASSIGN_PAGE_SIZE).get_page(request.GET.get("page"))

    return render(request, "app_projects/assign.html", {
        "page_obj": page_obj,
        "search_query": search,
        "project_filter": project_filter,
        "target_projects": _assignable_projects(org),
        "filter_projects": Project.objects.filter(organization=org).order_by("name"),
        "can_manage": True,
    })
