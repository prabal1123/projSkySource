import re
import uuid

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower
from django.conf import settings
from appEmp.fields import EncryptedTextField


class Project(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_ON_HOLD = "on_hold"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_ON_HOLD, "On hold"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    organization = models.ForeignKey(
        "app_organizations.Organization",
        on_delete=models.PROTECT,
        related_name="projects",
    )
    name = models.CharField(max_length=150)
    code = models.CharField(
        max_length=20,
        validators=[
            RegexValidator(
                r"^[A-Za-z0-9_-]+$",
                "Use only letters, digits, hyphen and underscore.",
            )
        ],
        help_text="Short code, for example PRY. Stored in upper case.",
    )
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE
    )
    lead = models.ForeignKey(
        "appEmp.empProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="led_projects",
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        permissions = [
            ("view_all_projects", "Can view all projects in the organization"),
            ("manage_projects", "Can create, edit and archive projects"),
        ]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                "organization",
                name="uniq_project_name_per_org_ci",
            ),
            models.UniqueConstraint(
                fields=["organization", "code"],
                name="uniq_project_code_per_org",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(start_date__isnull=True)
                    | models.Q(end_date__isnull=True)
                    | models.Q(end_date__gte=models.F("start_date"))
                ),
                name="project_end_not_before_start",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"

    @property
    def is_archived(self):
        return self.status == self.STATUS_ARCHIVED

    def _normalize(self):
        self.name = (self.name or "").strip()
        self.code = (self.code or "").strip().upper()

    def _check_lead(self):
        if (
            self.lead_id
            and self.organization_id
            and self.lead.organization_id != self.organization_id
        ):
            raise ValidationError(
                {"lead": "The project lead must belong to the same organization."}
            )

    def clean(self):
        super().clean()
        self._normalize()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError(
                {"end_date": "End date cannot be before the start date."}
            )
        self._check_lead()

    def save(self, *args, **kwargs):
        self._normalize()
        self._check_lead()
        super().save(*args, **kwargs)

    def archive(self):
        self.status = self.STATUS_ARCHIVED
        self.save(update_fields=["status", "updated_at"])


class Action(models.Model):
    STATUS_TODO = "todo"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_REVIEW = "review"
    STATUS_DONE = "done"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_TODO, "To do"),
        (STATUS_IN_PROGRESS, "In progress"),
        (STATUS_REVIEW, "Review"),
        (STATUS_DONE, "Done"),
        (STATUS_CANCELLED, "Cancelled"),
    ]
    OPEN_STATUSES = (STATUS_TODO, STATUS_IN_PROGRESS, STATUS_REVIEW)

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    organization = models.ForeignKey(
        "app_organizations.Organization",
        on_delete=models.PROTECT,
        related_name="actions",
    )
    project = models.ForeignKey(
        Project, on_delete=models.PROTECT, related_name="actions"
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="subtasks",
    )
    title = models.CharField(max_length=200)
    description = EncryptedTextField(blank=True)
    assignee = models.ForeignKey(
        "appEmp.empProfile",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assigned_actions",
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_TODO
    )
    due_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["project", "status"], name="action_project_status_idx"),
            models.Index(fields=["assignee", "status"], name="action_assignee_status_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(parent__isnull=True)
                | ~models.Q(pk=models.F("parent")),
                name="action_parent_not_self",
            ),
        ]

    def __str__(self):
        return self.title

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    @property
    def is_subtask(self):
        return self.parent_id is not None

    @property
    def needs_reassign(self):
        """True when the assignee left the project or was deactivated."""
        if not self.is_open or not self.assignee_id:
            return False
        person = self.assignee
        return (not person.is_active) or person.project_id != self.project_id

    def _check_consistency(self):
        errors = {}
        if self.project_id:
            if not self.organization_id:
                self.organization_id = self.project.organization_id
            elif self.project.organization_id != self.organization_id:
                errors["project"] = "The project belongs to a different organization."
        if (
            self.assignee_id
            and self.organization_id
            and self.assignee.organization_id != self.organization_id
        ):
            errors["assignee"] = "The assignee must belong to the same organization."
        if self.parent_id:
            parent = self.parent
            if self.pk and parent.pk == self.pk:
                errors["parent"] = "An action cannot be its own parent."
            elif parent.project_id != self.project_id:
                errors["parent"] = "A subtask must be in the same project as its parent."
            elif parent.parent_id:
                errors["parent"] = "Subtasks can only be one level deep."
            elif self.pk and self.subtasks.exists():
                errors["parent"] = "An action that has subtasks cannot become a subtask."
        if errors:
            raise ValidationError(errors)

    def clean(self):
        super().clean()
        self.title = (self.title or "").strip()
        self._check_consistency()

    def save(self, *args, **kwargs):
        self.title = (self.title or "").strip()
        self._check_consistency()
        super().save(*args, **kwargs)


class ActionEvent(models.Model):
    KIND_CREATED = "created"
    KIND_STATUS = "status"
    KIND_ASSIGNEE = "assignee"
    KIND_EDITED = "edited"
    KIND_CHOICES = [
        (KIND_CREATED, "Created"),
        (KIND_STATUS, "Status changed"),
        (KIND_ASSIGNEE, "Assignee changed"),
        (KIND_EDITED, "Edited"),
    ]

    action = models.ForeignKey(
        Action, on_delete=models.CASCADE, related_name="events"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    from_value = models.CharField(max_length=100, blank=True)
    to_value = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
