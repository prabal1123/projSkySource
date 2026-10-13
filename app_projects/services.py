"""
Rules for actions (tasks) inside a project.

Views call these functions and never change an action directly. Each one
checks who may do it, checks the data, and writes an ActionEvent.
PermissionDenied means "you may not"; ValidationError means "that is invalid".
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from appEmp.models import empProfile

from .access import can_manage_projects
from .models import Action, ActionEvent

TITLE_MAX = 200
EDITABLE_FIELDS = ("title", "description", "due_date")


def _own_profile_id(user, org):
    return (
        empProfile.objects
        .filter(user=user, organization=org, is_active=True)
        .values_list("pk", flat=True)
        .first()
    )


def _require_manager(actor, org):
    if not can_manage_projects(actor, org):
        raise PermissionDenied("You may not manage actions in this project.")


def can_change_status(actor, action):
    if can_manage_projects(actor, action.organization):
        return True
    return bool(
        action.assignee_id
        and action.assignee_id == _own_profile_id(actor, action.organization)
    )


def _require_writable(project):
    if project.is_archived:
        raise ValidationError("This project is archived, so its actions are read-only.")


def _clean_title(title):
    title = (title or "").strip()
    if not title:
        raise ValidationError({"title": "A title is required."})
    if len(title) > TITLE_MAX:
        raise ValidationError({"title": "The title is too long (200 characters at most)."})
    return title


def validate_assignee(project, assignee):
    """The assignee must be an active person on this project, same organization."""
    if assignee.organization_id != project.organization_id:
        raise ValidationError({"assignee": "The assignee must belong to the same organization."})
    if assignee.project_id != project.pk:
        raise ValidationError({"assignee": "The assignee must be on this project's team."})
    if not assignee.is_active:
        raise ValidationError({"assignee": "The assignee is not active."})


def _lock(action):
    return (
        Action.objects
        .select_for_update(of=("self",))
        .select_related("project", "organization")
        .get(pk=action.pk)
    )


def _event(action, actor, kind, from_value="", to_value=""):
    ActionEvent.objects.create(
        action=action,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        kind=kind,
        from_value=str(from_value or ""),
        to_value=str(to_value or ""),
    )


@transaction.atomic
def create_action(*, project, actor, title, description="", assignee=None,
                  due_date=None, parent=None):
    _require_manager(actor, project.organization)
    _require_writable(project)
    title = _clean_title(title)
    if assignee is not None:
        validate_assignee(project, assignee)
    action = Action.objects.create(
        organization=project.organization,
        project=project,
        parent=parent,
        title=title,
        description=description or "",
        assignee=assignee,
        due_date=due_date,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    _event(action, actor, ActionEvent.KIND_CREATED, "", action.status)
    return action


@transaction.atomic
def update_action(action, actor, **changes):
    unknown = set(changes) - set(EDITABLE_FIELDS)
    if unknown:
        raise ValidationError("Cannot edit: %s." % ", ".join(sorted(unknown)))
    action = _lock(action)
    _require_manager(actor, action.organization)
    _require_writable(action.project)
    changed = []
    for field, value in changes.items():
        if field == "title":
            value = _clean_title(value)
        if field == "description":
            value = value or ""
        if getattr(action, field) != value:
            setattr(action, field, value)
            changed.append(field)
    if changed:
        action.save()
        _event(action, actor, ActionEvent.KIND_EDITED, "", ",".join(changed))
    return action


@transaction.atomic
def reassign(action, assignee, actor):
    """Set a new assignee, or None to unassign on purpose."""
    action = _lock(action)
    _require_manager(actor, action.organization)
    _require_writable(action.project)
    if assignee is not None:
        validate_assignee(action.project, assignee)
    new_id = assignee.pk if assignee is not None else None
    if new_id == action.assignee_id:
        return action
    old_id = action.assignee_id
    action.assignee = assignee
    action.save(update_fields=["assignee", "updated_at"])
    _event(action, actor, ActionEvent.KIND_ASSIGNEE, old_id, new_id)
    return action


@transaction.atomic
def change_status(action, new_status, actor):
    """The only way status changes."""
    if not isinstance(new_status, str) or new_status not in dict(Action.STATUS_CHOICES):
        raise ValidationError({"status": "Choose a valid status."})
    action = _lock(action)
    if not can_change_status(actor, action):
        raise PermissionDenied("Only the assignee or a project manager can change the status.")
    _require_writable(action.project)
    old = action.status
    if old == new_status:
        return action
    action.status = new_status
    action.completed_at = timezone.now() if new_status == Action.STATUS_DONE else None
    action.save(update_fields=["status", "completed_at", "updated_at"])
    _event(action, actor, ActionEvent.KIND_STATUS, old, new_status)
    return action


@transaction.atomic
def delete_action(action, actor):
    action = _lock(action)
    _require_manager(actor, action.organization)
    _require_writable(action.project)
    action.delete()


def actions_needing_reassign(project):
    """Open actions whose assignee left the project or was deactivated."""
    return (
        Action.objects
        .filter(project=project, status__in=Action.OPEN_STATUSES, assignee__isnull=False)
        .filter(~Q(assignee__project=project) | Q(assignee__is_active=False))
    )
