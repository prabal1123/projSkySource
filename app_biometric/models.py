from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class BiometricDevice(models.Model):
    """One physical Smart Office device, identified by its serial number."""

    organization = models.ForeignKey(
        "app_organizations.Organization",
        on_delete=models.CASCADE,
        related_name="biometric_devices",
    )
    serial_number = models.CharField(max_length=64)
    name = models.CharField(max_length=120, blank=True)
    project = models.ForeignKey(
        "app_projects.Project",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="biometric_devices",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["serial_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "serial_number"],
                name="uniq_biodevice_org_serial",
            ),
        ]

    def __str__(self):
        return self.name or self.serial_number

    def clean(self):
        super().clean()
        if (
            self.project_id
            and self.organization_id
            and self.project.organization_id != self.organization_id
        ):
            raise ValidationError(
                {"project": "This project belongs to a different organization."}
            )


class BiometricIdentity(models.Model):
    """Maps the code a device reports (Smart Office EmployeeCode) to an employee.

    employee stays empty until the person is linked, so punches are never lost.
    """

    organization = models.ForeignKey(
        "app_organizations.Organization",
        on_delete=models.CASCADE,
        related_name="biometric_identities",
    )
    device_code = models.CharField(max_length=64)
    employee = models.ForeignKey(
        "appEmp.empProfile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="biometric_identities",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["device_code"]
        verbose_name_plural = "biometric identities"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "device_code"],
                name="uniq_bioidentity_org_code",
            ),
            models.UniqueConstraint(
                fields=["organization", "employee"],
                condition=models.Q(employee__isnull=False),
                name="uniq_bioidentity_org_employee",
            ),
        ]

    def __str__(self):
        return self.device_code

    def clean(self):
        super().clean()
        if (
            self.employee_id
            and self.organization_id
            and self.employee.organization_id != self.organization_id
        ):
            raise ValidationError(
                {"employee": "This employee belongs to a different organization."}
            )


class PunchLog(models.Model):
    """One raw punch from a device. Never edited; duplicates are ignored."""

    organization = models.ForeignKey(
        "app_organizations.Organization",
        on_delete=models.CASCADE,
        related_name="punch_logs",
    )
    device = models.ForeignKey(
        BiometricDevice,
        on_delete=models.PROTECT,
        related_name="punches",
    )
    employee_code = models.CharField(max_length=64)
    punch_time = models.DateTimeField()
    direction = models.CharField(max_length=16, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-punch_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["device", "employee_code", "punch_time"],
                name="uniq_punch_device_code_time",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "employee_code", "punch_time"],
                name="punch_org_code_time_idx",
            ),
            models.Index(
                fields=["organization", "punch_time"],
                name="punch_org_time_idx",
            ),
        ]

    def __str__(self):
        return f"{self.employee_code} @ {self.punch_time:%Y-%m-%d %H:%M:%S}"


class SyncRun(models.Model):
    """Audit trail of each pull from Smart Office. Counts only, no secrets."""

    MODE_DAILY = "daily"
    MODE_RANGE = "range"
    MODE_CHOICES = [(MODE_DAILY, "Daily"), (MODE_RANGE, "Range / backfill")]

    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_RUNNING, "Running"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_FAILED, "Failed"),
    ]

    organization = models.ForeignKey(
        "app_organizations.Organization",
        on_delete=models.CASCADE,
        related_name="biometric_sync_runs",
    )
    mode = models.CharField(max_length=10, choices=MODE_CHOICES)
    from_date = models.DateField()
    to_date = models.DateField()
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=STATUS_RUNNING
    )
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    api_calls = models.PositiveIntegerField(default=0)
    records_fetched = models.PositiveIntegerField(default=0)
    records_new = models.PositiveIntegerField(default=0)
    records_skipped = models.PositiveIntegerField(default=0)
    error_message = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.mode} {self.from_date}..{self.to_date} [{self.status}]"
