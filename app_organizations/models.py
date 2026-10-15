from django.conf import settings
from django.db import models


class Organization(models.Model):
    name = models.CharField(max_length=150)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="organizations_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class OrganizationMember(models.Model):
    ROLE_CHOICES = [
        ("owner", "Owner"),
        ("admin", "Admin"),
        ("manager", "Manager"),
        ("member", "Member"),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="members"
    )
    # OneToOne: in Pro a user belongs to exactly one organization.
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="organization_membership",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="member")
    joined_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.organization.name} ({self.role})"


class OrganizationModule(models.Model):
    SOURCE_CHOICES = [
        ("manual", "Manual"),
        ("trial", "Trial"),
        ("plan", "Plan"),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="modules"
    )
    # Validated against modules.MODULES in the admin form, not via
    # field choices, so adding a module never needs a migration.
    module_key = models.CharField(max_length=40)
    is_enabled = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="manual")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["module_key"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "module_key"], name="uniq_org_module"
            )
        ]

    def __str__(self):
        return f"{self.organization.name}: {self.module_key}"
