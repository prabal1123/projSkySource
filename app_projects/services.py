"""
Rules for actions (tasks) inside a project.

Views call these functions and never change an action directly. Each one
checks who may do it, checks the data, and writes an ActionEvent.
PermissionDenied means "you may not"; ValidationError means "that is invalid".
"""

import io
import os
import zipfile

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from appEmp.models import empProfile

from .access import can_manage_projects
from .models import Action, ActionAttachment, ActionComment, ActionEvent

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


COMMENT_MAX = 5000
ATTACH_MAX_BYTES = 200 * 1024
ATTACH_MAX_PER_ACTION = 20
ZIP_MAX_UNCOMPRESSED = 20 * 1024 * 1024
ATTACH_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _require_member(actor, org):
    if not (can_manage_projects(actor, org) or _own_profile_id(actor, org)):
        raise PermissionDenied("You are not part of this organization.")


def _lock_child(model, obj):
    return (
        model.objects
        .select_for_update(of=("self",))
        .select_related("action__project", "organization")
        .get(pk=obj.pk)
    )


def _clean_comment(body):
    body = (body or "").strip()
    if not body:
        raise ValidationError({"body": "Write something first."})
    if len(body) > COMMENT_MAX:
        raise ValidationError({"body": "The comment is too long (5000 characters at most)."})
    return body


def _is_owner_or_manager(actor, org, owner_id):
    if can_manage_projects(actor, org):
        return True
    return bool(owner_id and owner_id == getattr(actor, "pk", None))


def can_modify_comment(actor, comment):
    return _is_owner_or_manager(actor, comment.organization, comment.author_id)


def can_delete_attachment(actor, attachment):
    return _is_owner_or_manager(actor, attachment.organization, attachment.uploaded_by_id)


@transaction.atomic
def add_comment(action, actor, body):
    action = _lock(action)
    _require_member(actor, action.organization)
    _require_writable(action.project)
    return ActionComment.objects.create(
        action=action,
        organization=action.organization,
        author=actor if getattr(actor, "is_authenticated", False) else None,
        body=_clean_comment(body),
    )


@transaction.atomic
def update_comment(comment, actor, body):
    comment = _lock_child(ActionComment, comment)
    if not can_modify_comment(actor, comment):
        raise PermissionDenied("Only the author or a project manager can change this comment.")
    _require_writable(comment.action.project)
    comment.body = _clean_comment(body)
    comment.edited_at = timezone.now()
    comment.save(update_fields=["body", "edited_at"])
    return comment


@transaction.atomic
def delete_comment(comment, actor):
    comment = _lock_child(ActionComment, comment)
    if not can_modify_comment(actor, comment):
        raise PermissionDenied("Only the author or a project manager can delete this comment.")
    _require_writable(comment.action.project)
    comment.delete()


def _signature_ok(ext, data):
    if ext == ".pdf":
        return data.startswith(b"%PDF-")
    if ext == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in (".jpg", ".jpeg"):
        return data.startswith(b"\xff\xd8\xff")
    if ext == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                infos = z.infolist()
                names = [i.filename for i in infos]
                if sum(i.file_size for i in infos) > ZIP_MAX_UNCOMPRESSED:
                    return False
                return "[Content_Types].xml" in names and any(
                    n.startswith("word/") for n in names
                )
        except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError):
            return False
    return False


def _validate_upload(upload):
    if upload is None:
        raise ValidationError({"file": "Choose a file to upload."})
    name = os.path.basename((upload.name or "").replace("\\", "/")).strip()
    name = "".join(ch for ch in name if ch.isprintable())
    ext = os.path.splitext(name)[1].lower()
    if ext not in ATTACH_TYPES:
        raise ValidationError({"file": "Only pdf, jpg, png and docx files are allowed."})
    if upload.size > ATTACH_MAX_BYTES:
        raise ValidationError({"file": "The file is too large (200 KB at most)."})
    upload.seek(0)
    data = upload.read(ATTACH_MAX_BYTES + 1)
    if not data:
        raise ValidationError({"file": "The file is empty."})
    if len(data) > ATTACH_MAX_BYTES:
        raise ValidationError({"file": "The file is too large (200 KB at most)."})
    if not _signature_ok(ext, data):
        raise ValidationError({"file": "The file content does not match its type."})
    if len(name) > 200:
        name = name[: 200 - len(ext)] + ext
    return name, ext, data


@transaction.atomic
def add_attachment(action, actor, upload):
    action = _lock(action)
    _require_member(actor, action.organization)
    _require_writable(action.project)
    name, ext, data = _validate_upload(upload)
    if action.attachments.count() >= ATTACH_MAX_PER_ACTION:
        raise ValidationError({"file": "This action already has 20 attachments."})
    att = ActionAttachment(
        action=action,
        organization=action.organization,
        uploaded_by=actor if getattr(actor, "is_authenticated", False) else None,
        original_name=name,
        content_type=ATTACH_TYPES[ext],
        size=len(data),
    )
    att.file.save(name, ContentFile(data), save=False)
    try:
        att.save()
    except Exception:
        att.file.delete(save=False)
        raise
    return att


@transaction.atomic
def delete_attachment(attachment, actor):
    attachment = _lock_child(ActionAttachment, attachment)
    if not can_delete_attachment(actor, attachment):
        raise PermissionDenied("Only the uploader or a project manager can delete this file.")
    _require_writable(attachment.action.project)
    attachment.delete()
