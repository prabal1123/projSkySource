from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .access import (
    can_manage_projects,
    can_view_all_projects,
    get_visible_project_or_404,
    visible_projects,
)
from .forms import ProjectForm
from .models import Project


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
