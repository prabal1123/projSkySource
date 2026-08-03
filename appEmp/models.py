import uuid
from django.db import models
from django.contrib.auth.models import User
from datetime import time
from django.utils import timezone

ROLE_CHOICES = (
    ('SUPER_ADMIN','Super Admin'),
    ('HR_ADMIN','HR Admin'),
    ('RECRUITER','Recruiter'),
    ('HIRING_MANAGER','Hiring Manager'),
    ('TEAM_LEAD','Team Lead'),
    ('EMPLOYEE','Employee'),
)
ADMIN_ROLES = ['SUPER_ADMIN', 'HR_ADMIN', 'RECRUITER', 'HIRING_MANAGER', 'TEAM_LEAD']

class empProfile(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='EMPLOYEE')
    # first_name = models.CharField(max_length=30)
    # last_name = models.CharField(max_length=30)
    phone_number = models.CharField(max_length=15, null=True, blank=True)
    # email = models.EmailField(unique=True)
    position = models.CharField(max_length=50, null=True, blank=True)
    date_hired = models.DateField(null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    state = models.CharField(max_length=30, null=True, blank=True)
    zip_code = models.CharField(max_length=10, null=True, blank=True)
    is_address_verified = models.BooleanField(default=False)
    is_email_verified = models.BooleanField(default=False)
    is_phone_verified = models.BooleanField(default=False)
    is_background_check_completed = models.BooleanField(default=False)
    is_aadhar_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Employee"
        verbose_name_plural = "Employees"

    def __str__(self):
        return f"{self.user.first_name} {self.user.last_name}"



ATTENDANCE_STATUS_CHOICES = (
    ('PRESENT', 'Present'),
    ('LATE', 'Late'),
    ('HALF_DAY', 'Half Day'),
    ('ABSENT', 'Absent'),
    ('LEAVE', 'On Leave'),
)

LATE_CUTOFF_TIME = time(10, 15)  # after this time, check-in counts as Late


class Attendance(models.Model):
    employee = models.ForeignKey(
        empProfile, on_delete=models.CASCADE, related_name="attendances"
    )
    date = models.DateField(default=timezone.localdate)
    check_in = models.DateTimeField(null=True, blank=True)
    check_out = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=10, choices=ATTENDANCE_STATUS_CHOICES, default='ABSENT'
    )
    marked_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="attendance_marked", help_text="Admin who manually edited this record, if any"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('employee', 'date')
        ordering = ['-date']
        verbose_name = "Attendance"
        verbose_name_plural = "Attendance Records"

    def __str__(self):
        return f"{self.employee} - {self.date} - {self.get_status_display()}"
