import uuid as uuid_lib
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.urls import reverse
from django.utils import timezone

from appEmp.models import empProfile

from . import services
from .access import can_manage_projects, get_visible_project_or_404, visible_projects
from .action_forms import ActionForm, ReassignForm
from .models import Action
from .views import _current_org, _require_manage

PAGE_SIZE = 25


def _list_url(project, **params):
    url = reverse("projectActionList", args=[project.uuid])
    query = urlencode({k: v for k, v in params.items() if v})
    return url + ("?" + query if query else "")


def _detail_url(project, action):
    return reverse("projectActionDetail", args=[project.uuid, action.uuid])


def _can_edit(request, org, project):
    return can_manage_projects(request.user, org) and not project.is_archived


def _get_action(project, action_uuid):
    return get_object_or_404(
        Action.objects.select_related(
            "assignee__user", "parent", "project", "organization", "created_by"
        ),
        project=project,
        organization=project.organization,
        uuid=action_uuid,
    )


def _form_errors(form, exc):
    if hasattr(exc, "error_dict"):
        for field, errors in exc.message_dict.items():
            form.add_error(field if field in form.fields else None, errors)
    else:
        form.add_error(None, exc.messages)


def _person_name(profile):
    return profile.user.get_full_name() or profile.user.username


def _history(events, org):
    status_labels = dict(Action.STATUS_CHOICES)
    ids = set()
    for e in events:
        if e.kind == "assignee":
            for value in (e.from_value, e.to_value):
                if value.isdigit():
                    ids.add(int(value))
    names = {
        p.pk: _person_name(p)
        for p in empProfile.objects.filter(organization=org, pk__in=ids).select_related("user")
    }

    def who(value):
        return names.get(int(value), "Unknown") if value.isdigit() else "Unassigned"

    lines = []
    for e in events:
        if e.kind == "created":
            text = "Created as %s" % status_labels.get(e.to_value, e.to_value)
        elif e.kind == "status":
            text = "Status: %s to %s" % (
                status_labels.get(e.from_value, e.from_value),
                status_labels.get(e.to_value, e.to_value),
            )
        elif e.kind == "assignee":
            text = "Assignee: %s to %s" % (who(e.from_value), who(e.to_value))
        else:
            text = "Edited: %s" % e.to_value.replace(",", ", ")
        lines.append({
            "when": e.created_at,
            "who": (e.actor.get_full_name() or e.actor.username) if e.actor else "System",
            "text": text,
        })
    return lines


@login_required
def action_list_view(request, uuid):
    org = _current_org(request)
    project = get_visible_project_or_404(request, uuid)

    status = request.GET.get("status", "")
    if status not in dict(Action.STATUS_CHOICES):
        status = ""
    q = (request.GET.get("q") or "").replace("\x00", "").strip()[:100]
    assignee_raw = (request.GET.get("assignee") or "").strip()
    assignee, assignee_uuid = "", None
    if assignee_raw == "unassigned":
        assignee = "unassigned"
    else:
        try:
            assignee_uuid = uuid_lib.UUID(assignee_raw)
            assignee = str(assignee_uuid)
        except ValueError:
            pass

    top = Action.objects.filter(project=project, organization=org, parent__isnull=True)
    counts = dict(top.order_by().values_list("status").annotate(n=Count("pk")))

    actions = top.select_related("assignee__user").annotate(subtask_count=Count("subtasks"))
    if status:
        actions = actions.filter(status=status)
    if assignee == "unassigned":
        actions = actions.filter(assignee__isnull=True)
    elif assignee_uuid:
        actions = actions.filter(assignee__uuid=assignee_uuid)
    if q:
        actions = actions.filter(title__icontains=q)
    page = Paginator(actions.order_by("-created_at", "-pk"), PAGE_SIZE).get_page(
        request.GET.get("page")
    )

    tabs = [{
        "label": "All",
        "count": sum(counts.values()),
        "url": _list_url(project, q=q, assignee=assignee),
        "active": status == "",
    }]
    for value, label in Action.STATUS_CHOICES:
        tabs.append({
            "label": label,
            "count": counts.get(value, 0),
            "url": _list_url(project, status=value, q=q, assignee=assignee),
            "active": status == value,
        })

    team = (
        project.employees.filter(is_active=True)
        .select_related("user")
        .order_by("user__first_name", "user__last_name")
    )
    return render(request, "app_projects/action_list.html", {
        "project": project,
        "page": page,
        "tabs": tabs,
        "team": team,
        "status": status,
        "q": q,
        "assignee": assignee,
        "base_query": urlencode(
            {k: v for k, v in (("status", status), ("q", q), ("assignee", assignee)) if v}
        ),
        "can_edit": _can_edit(request, org, project),
        "today": timezone.localdate(),
    })


@login_required
def action_detail_view(request, uuid, action_uuid):
    org = _current_org(request)
    project = get_visible_project_or_404(request, uuid)
    action = _get_action(project, action_uuid)
    subtasks = list(
        action.subtasks.select_related("assignee__user").order_by("created_at", "pk")
    )
    events = list(action.events.select_related("actor"))
    return render(request, "app_projects/action_detail.html", {
        "project": project,
        "action": action,
        "subtasks": subtasks,
        "history": _history(events, org),
        "can_change_status": services.can_change_status(request.user, action) and not project.is_archived,
        "status_choices": Action.STATUS_CHOICES,
        "reassign_form": ReassignForm(project=project, initial={"assignee": action.assignee_id}) if _can_edit(request, org, project) else None,
        "can_edit": _can_edit(request, org, project),
        "today": timezone.localdate(),
    })


@login_required
def action_create_view(request, uuid):
    org = _current_org(request)
    project = get_visible_project_or_404(request, uuid)
    _require_manage(request, org)
    if project.is_archived:
        messages.error(request, "This project is archived, so its actions are read-only.")
        return redirect(_list_url(project))

    form = ActionForm(
        request.POST if request.method == "POST" else None, project=project
    )
    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        try:
            action = services.create_action(
                project=project,
                actor=request.user,
                title=cd["title"],
                description=cd["description"],
                assignee=cd["assignee"],
                due_date=cd["due_date"],
            )
        except ValidationError as exc:
            _form_errors(form, exc)
        else:
            messages.success(request, "Action created.")
            return redirect(_detail_url(project, action))
    return render(request, "app_projects/action_form.html", {
        "form": form,
        "project": project,
        "page_title": "New action",
        "cancel_url": _list_url(project),
    })


@login_required
def action_edit_view(request, uuid, action_uuid):
    org = _current_org(request)
    project = get_visible_project_or_404(request, uuid)
    action = _get_action(project, action_uuid)
    _require_manage(request, org)
    if project.is_archived:
        messages.error(request, "This project is archived, so its actions are read-only.")
        return redirect(_detail_url(project, action))

    form = ActionForm(
        request.POST if request.method == "POST" else None,
        initial={
            "title": action.title,
            "description": action.description,
            "assignee": action.assignee_id,
            "due_date": action.due_date,
        },
        project=project,
        current_assignee_id=action.assignee_id,
    )
    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        new_assignee = cd["assignee"]
        try:
            with transaction.atomic():
                services.update_action(
                    action,
                    request.user,
                    title=cd["title"],
                    description=cd["description"],
                    due_date=cd["due_date"],
                )
                if (new_assignee.pk if new_assignee else None) != action.assignee_id:
                    services.reassign(action, new_assignee, request.user)
        except ValidationError as exc:
            _form_errors(form, exc)
        else:
            messages.success(request, "Action updated.")
            return redirect(_detail_url(project, action))
    return render(request, "app_projects/action_form.html", {
        "form": form,
        "project": project,
        "page_title": "Edit action",
        "cancel_url": _detail_url(project, action),
    })


@login_required
def my_actions_view(request):
    org = _current_org(request)
    profile_id = (
        empProfile.objects
        .filter(user=request.user, organization=org, is_active=True)
        .values_list("pk", flat=True)
        .first()
    )
    show_done = request.GET.get("done") == "1"
    actions = Action.objects.none()
    if profile_id:
        actions = Action.objects.filter(
            organization=org,
            assignee_id=profile_id,
            project__in=visible_projects(request),
        ).select_related("project", "assignee__user")
        if not show_done:
            actions = actions.filter(status__in=Action.OPEN_STATUSES)
        actions = actions.order_by(F("due_date").asc(nulls_last=True), "-created_at", "-pk")
    page = Paginator(actions, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "app_projects/my_actions.html", {
        "page": page,
        "show_done": show_done,
        "today": timezone.localdate(),
    })



@login_required
@require_POST
def action_status_view(request, uuid, action_uuid):
    project = get_visible_project_or_404(request, uuid)
    action = _get_action(project, action_uuid)
    try:
        services.change_status(action, request.POST.get("status"), request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "Status updated.")
    return redirect(_detail_url(project, action))


@login_required
@require_POST
def action_reassign_view(request, uuid, action_uuid):
    org = _current_org(request)
    project = get_visible_project_or_404(request, uuid)
    action = _get_action(project, action_uuid)
    _require_manage(request, org)
    form = ReassignForm(request.POST, project=project)
    if not form.is_valid():
        messages.error(request, "Choose a person on this project's team, or Unassigned.")
        return redirect(_detail_url(project, action))
    try:
        services.reassign(action, form.cleaned_data["assignee"], request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "Assignee updated.")
    return redirect(_detail_url(project, action))


@login_required
@require_POST
def action_delete_view(request, uuid, action_uuid):
    org = _current_org(request)
    project = get_visible_project_or_404(request, uuid)
    action = _get_action(project, action_uuid)
    _require_manage(request, org)
    try:
        services.delete_action(action, request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect(_detail_url(project, action))
    messages.success(request, "Action deleted.")
    return redirect(_list_url(project))
