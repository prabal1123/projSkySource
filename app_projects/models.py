import re
import uuid

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower


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
