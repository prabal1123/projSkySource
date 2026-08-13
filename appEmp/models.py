import uuid
from django.db import models
from django.contrib.auth.models import User
from datetime import time
from django.utils import timezone
from decimal import Decimal
from django.core.exceptions import ValidationError
import calendar


def add_calendar_months(source_date, months):
    """
    Add calendar months while keeping the date valid.

    Example:
    31 Aug + 3 months -> 30 Nov
    """
    month_index = source_date.month - 1 + months

    year = source_date.year + month_index // 12
    month = month_index % 12 + 1

    day = min(
        source_date.day,
        calendar.monthrange(year, month)[1],
    )

    return source_date.replace(
        year=year,
        month=month,
        day=day,
    )



class empProfile(models.Model):
    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False
    )

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE
    )

    # role = models.CharField(
    #     max_length=20,
    #     choices=ROLE_CHOICES,
    #     default="EMPLOYEE"
    # )

    manager = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="team_members",
        help_text="Reporting manager or immediate superior of this employee."
    )

    designation = models.ForeignKey(
        "DesignationMaster",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees"
    )

    shift = models.ForeignKey(
        "ShiftMaster",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees"
    )
    work_schedule = models.ForeignKey(
    "WorkSchedule",
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="employees"
)

    is_default_manager = models.BooleanField(
        default=False,
        help_text=(
            "New employees will automatically report to this employee. "
            "Only one active employee can be the default manager."
        )
    )

    phone_number = models.CharField(
        max_length=15,
        null=True,
        blank=True
    )

    position = models.CharField(
        max_length=50,
        null=True,
        blank=True
    )

    date_hired = models.DateField(
        null=True,
        blank=True
    )

    leave_eligible_from = models.DateField(
    null=True,
    blank=True,
    help_text=(
        "Date from which the employee becomes eligible "
        "to use the leave facility."
        ),
    )

    address = models.TextField(
        null=True,
        blank=True
    )

    state = models.CharField(
        max_length=30,
        null=True,
        blank=True
    )

    zip_code = models.CharField(
        max_length=10,
        null=True,
        blank=True
    )

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
        ordering = ["user__first_name", "user__last_name"]
        permissions = [
        (
            "view_hr_dashboard",
            "Can view HR dashboard",
        ),
        (
            "manage_employees",
            "Can manage employees",
        ),
        (
            "manage_attendance",
            "Can manage attendance",
        ),
        (
            "review_leave",
            "Can review leave requests",
        ),
        (
            "manage_leave_balance",
            "Can manage leave balances",
        ),
        (
            "review_attendance_exception",
            "Can review attendance exceptions",
        ),
        (
            "manage_salary",
            "Can manage salary",
        ),

        # Clearance / NOC permissions
        (
            "view_all_clearance_requests",
            "Can view all clearance requests",
        ),
        (
            "apply_clearance_for_employee",
            "Can apply clearance for an employee",
        ),
        (
            "review_finance_noc",
            "Can review finance NOC requests",
        ),
        (
            "initiate_employee_exit",
            "Can initiate employee exit",
        ),
        (
            "finalize_employee_exit",
            "Can finalize employee exit",
        ),
    ]

    def clean(self):
        """
        Prevent an employee from being assigned as their own manager.
        """
        super().clean()

        if self.manager_id and self.manager_id == self.pk:
            raise ValidationError({
                "manager": "An employee cannot be their own manager."
            })

    def save(self, *args, **kwargs):
        """
        Ensure only one employee is marked as the default manager.
        """
        if self.is_default_manager:
            empProfile.objects.filter(
                is_default_manager=True
            ).exclude(
                pk=self.pk
            ).update(
                is_default_manager=False
            )

        if not self.work_schedule_id:
            default_schedule = WorkSchedule.objects.filter(
                is_default=True,
                is_active=True
            ).first()

            if default_schedule:
                self.work_schedule = default_schedule

        super().save(*args, **kwargs)

    @property
    def default_leave_eligible_from(self):
        """
        Default company leave policy:
        employee becomes leave-eligible after
        completing 3 calendar months from date of joining.
        """
        if not self.date_hired:
            return None

        return add_calendar_months(
            self.date_hired,
            3,
        )

    @property
    def effective_leave_eligible_from(self):
        """
        HR-selected eligibility date takes priority.

        If HR has not provided an override,
        use the default 3-month probation rule.
        """
        if self.leave_eligible_from:
            return self.leave_eligible_from

        return self.default_leave_eligible_from

    @property
    def is_leave_eligible(self):
        """
        True once the employee reaches their
        effective leave eligibility date.
        """
        eligible_from = self.effective_leave_eligible_from

        if not eligible_from:
            return False

        return timezone.localdate() >= eligible_from

    def __str__(self):
        full_name = self.user.get_full_name().strip()

        if full_name:
            return full_name

        return self.user.username

ATTENDANCE_STATUS_CHOICES = (
    ('PRESENT', 'Present'),
    ('LATE', 'Late'),
    ('HALF_DAY', 'Half Day'),
    ('ABSENT', 'Absent'),
    ('LEAVE', 'On Leave'),
)

LATE_CUTOFF_TIME = time(10, 15)  # after this time, check-in counts as Late


class Attendance(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
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


ATTENDANCE_EXCEPTION_STATUS_CHOICES = (
    ("PENDING", "Pending"),
    ("APPROVED", "Approved"),
    ("REJECTED", "Rejected"),
)


class AttendanceException(models.Model):
    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False
    )

    attendance = models.ForeignKey(
        Attendance,
        on_delete=models.CASCADE,
        related_name="exception_requests"
    )

    raised_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="attendance_exceptions_raised"
    )

    reason = models.TextField()

    status = models.CharField(
        max_length=10,
        choices=ATTENDANCE_EXCEPTION_STATUS_CHOICES,
        default="PENDING"
    )

    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_exceptions_reviewed"
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True
    )

    manager_comment = models.TextField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Attendance Exception"
        verbose_name_plural = "Attendance Exceptions"

        constraints = [
            models.UniqueConstraint(
                fields=["attendance", "raised_by"],
                condition=models.Q(status="PENDING"),
                name="unique_pending_attendance_exception"
            )
        ]

    def __str__(self):
        return (
            f"{self.attendance.employee} - "
            f"{self.attendance.date} - "
            f"{self.get_status_display()}"
        )


class Salary(models.Model):
    """
    One row per salary revision. Only one row per employee has is_active=True
    at any time — that's the 'current' salary. Keeping history instead of
    overwriting means you can later show raise history / generate slips for
    past months using the salary that was active then, if you want.
    """
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    employee = models.ForeignKey(
        empProfile,
        on_delete=models.CASCADE,
        related_name='salary_records',
    )
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2)
    hra = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pf = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # employee contribution — deducted, not added

    effective_date = models.DateField(default=timezone.now)
    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        User,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='salaries_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-effective_date', '-created_at']

    def __str__(self):
        return f"{self.employee.user.get_full_name() or self.employee.user.username} — {self.effective_date}"

    def save(self, *args, **kwargs):
        # Enforce "only one active record per employee" at save time.
        if self.is_active:
            Salary.objects.filter(
                employee=self.employee, is_active=True
            ).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    # ── Derived figures ────────────────────────────────────────────────
    @property
    def gross_monthly(self):
        return self.basic_salary + self.hra

    @property
    def ctc_monthly(self):
        """CTC = Basic + HRA only. PF is an employee deduction, NOT added to CTC."""
        return self.basic_salary + self.hra

    @property
    def ctc_annual(self):
        return self.ctc_monthly * 12

    def calculate_annual_tax(self):
        """
        SIMPLIFIED illustrative slab calc (India, new-regime-style slabs) +
        4% health & education cess, applied on annual gross (Basic + HRA).
        This is NOT a substitute for a real payroll/tax engine — confirm
        actual slabs and exemptions with your finance team before this
        feeds real payslips.
        """
        annual_taxable = self.gross_monthly * 12
        if annual_taxable < 0:
            annual_taxable = Decimal('0')

        slabs = [
            (Decimal('300000'), Decimal('0.00')),
            (Decimal('600000'), Decimal('0.05')),
            (Decimal('900000'), Decimal('0.10')),
            (Decimal('1200000'), Decimal('0.15')),
            (Decimal('1500000'), Decimal('0.20')),
            (Decimal('Infinity'), Decimal('0.30')),
        ]

        tax = Decimal('0')
        lower = Decimal('0')
        for upper, rate in slabs:
            if annual_taxable > lower:
                taxable_in_band = min(annual_taxable, upper) - lower
                tax += taxable_in_band * rate
                lower = upper
            else:
                break

        tax += tax * Decimal('0.04')  # cess
        return tax.quantize(Decimal('0.01'))

    def calculate_monthly_tds(self):
        return (self.calculate_annual_tax() / Decimal('12')).quantize(Decimal('0.01'))

    @property
    def net_monthly_pay(self):
        """Net Pay = Gross (Basic + HRA) minus PF (employee contribution) minus TDS."""
        return self.gross_monthly - self.pf - self.calculate_monthly_tds()

class WorkSchedule(models.Model):
    """
    Defines weekly working days for employees.

    Example:
    Monday-Friday = Working
    Saturday-Sunday = Weekly Off
    """

    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False
    )

    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Example: Standard 5-Day Week"
    )

    monday = models.BooleanField(default=True)
    tuesday = models.BooleanField(default=True)
    wednesday = models.BooleanField(default=True)
    thursday = models.BooleanField(default=True)
    friday = models.BooleanField(default=True)

    saturday = models.BooleanField(
        default=False
    )

    sunday = models.BooleanField(
        default=False
    )

    is_default = models.BooleanField(
        default=False,
        help_text=(
            "Default work schedule assigned to employees "
            "unless another schedule is selected."
        )
    )

    is_active = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        verbose_name = "Work Schedule"
        verbose_name_plural = "Work Schedules"
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if self.is_default:
            WorkSchedule.objects.filter(
                is_default=True
            ).exclude(
                pk=self.pk
            ).update(
                is_default=False
            )

        super().save(*args, **kwargs)

    def is_working_day(self, check_date):
        weekday_map = {
            0: self.monday,
            1: self.tuesday,
            2: self.wednesday,
            3: self.thursday,
            4: self.friday,
            5: self.saturday,
            6: self.sunday,
        }

        return weekday_map.get(
            check_date.weekday(),
            False
        )

    def __str__(self):
        return self.name
    

class ShiftMaster(models.Model):
    """
    Defines a work shift (timing). One shift can be flagged as the default —
    new employees get auto-assigned to it unless changed on their profile.
    """
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=50, unique=True)  # e.g. "General Shift", "Night Shift"
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_night_shift = models.BooleanField(
        default=False,
        help_text="Check if this shift spans midnight (e.g. 22:00–06:00)."
    )
    grace_period_minutes = models.PositiveIntegerField(
        default=0,
        help_text="Minutes of leeway after start_time before a check-in is marked Late."
    )
    is_default = models.BooleanField(
        default=False,
        help_text="New employees are auto-assigned this shift. Only one shift can be default."
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Shift"
        verbose_name_plural = "Shifts"

    def __str__(self):
        return f"{self.name} ({self.start_time.strftime('%H:%M')}–{self.end_time.strftime('%H:%M')})"

    def save(self, *args, **kwargs):
        # Enforce "only one default shift" — same pattern as Salary.is_active
        if self.is_default:
            ShiftMaster.objects.filter(
                is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


class DesignationMaster(models.Model):
    """Job designation lookup, e.g. 'Software Engineer', 'HR Manager'."""
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Designation"
        verbose_name_plural = "Designations"
        ordering = ['name']

    def __str__(self):
        return self.name


# class RoleMaster(models.Model):
#     """
#     Standalone role lookup table. Not yet wired into empProfile or permission
#     checks — this phase just creates the model per current requirements.
#     """
#     uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
#     name = models.CharField(max_length=100, unique=True)
#     description = models.TextField(null=True, blank=True)
#     is_active = models.BooleanField(default=True)
#     created_at = models.DateTimeField(auto_now_add=True)
#     updated_at = models.DateTimeField(auto_now=True)

#     class Meta:
#         verbose_name = "Role"
#         verbose_name_plural = "Roles"
#         ordering = ['name']

#     def __str__(self):
#         return self.name

# ── Leave Module: Phase 1 ──────────────────────────────────────────────

class LeaveTypeMaster(models.Model):
    """
    Defines leave types configured by HR.

    Examples:
    - Casual Leave (CL)
    - Sick Leave (SL)
    - Earned Leave (EL)
    - Loss of Pay (LOP)
    """

    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False
    )

    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Example: Casual Leave, Sick Leave, Earned Leave."
    )

    code = models.CharField(
        max_length=20,
        unique=True,
        help_text="Short unique code such as CL, SL, EL or LOP."
    )

    description = models.TextField(
        null=True,
        blank=True
    )

    is_paid = models.BooleanField(
        default=True,
        help_text="Uncheck for unpaid leave or loss-of-pay leave."
    )

    allow_half_day = models.BooleanField(
        default=False,
        help_text="Allow employees to apply for half-day leave."
    )

    requires_document = models.BooleanField(
        default=False,
        help_text="Require a supporting document while applying."
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Only active leave types will be available for assignment and requests."
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        verbose_name = "Leave Type"
        verbose_name_plural = "Leave Types"
        ordering = ["name"]

    def save(self, *args, **kwargs):
        # Keep codes consistent, e.g. "cl" becomes "CL".
        if self.code:
            self.code = self.code.strip().upper()

        # Remove accidental spaces around the name.
        if self.name:
            self.name = self.name.strip()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.code})"

# ── Leave Module: Phase 2 ──────────────────────────────────────────────

class LeaveBalance(models.Model):
    """
    Stores yearly leave allocation and usage for one employee
    and one leave type.
    """

    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False
    )

    employee = models.ForeignKey(
        empProfile,
        on_delete=models.CASCADE,
        related_name="leave_balances"
    )

    leave_type = models.ForeignKey(
        LeaveTypeMaster,
        on_delete=models.CASCADE,
        related_name="employee_balances"
    )

    year = models.PositiveIntegerField(
        default=timezone.now().year
    )

    total_allotted = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        default=0,
        help_text="Total leave days assigned to the employee for this year."
    )

    used = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        default=0,
        help_text="Approved leave days already used."
    )

    adjustment = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        default=0,
        help_text="Manual HR adjustment. Can be positive or negative."
    )

    assigned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leave_balances_assigned"
    )

    remarks = models.TextField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        verbose_name = "Leave Balance"
        verbose_name_plural = "Leave Balances"
        ordering = [
            "-year",
            "employee__user__first_name",
            "leave_type__name",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "employee",
                    "leave_type",
                    "year",
                ],
                name="unique_employee_leave_balance_per_year"
            )
        ]

    @property
    def available_balance(self):
        return (
            self.total_allotted
            + self.adjustment
            - self.used
        )

    def clean(self):
        super().clean()

        if self.total_allotted < 0:
            raise ValidationError({
                "total_allotted": "Total allotted leave cannot be negative."
            })

        if self.used < 0:
            raise ValidationError({
                "used": "Used leave cannot be negative."
            })

        if self.available_balance < 0:
            raise ValidationError(
                "Available leave balance cannot be negative."
            )

    def __str__(self):
        return (
            f"{self.employee} — "
            f"{self.leave_type.code} — "
            f"{self.year}"
        )


# ── Leave Module: Phase 3 ──────────────────────────────────────────────

LEAVE_REQUEST_STATUS_CHOICES = (
    ("PENDING", "Pending"),
    ("APPROVED", "Approved"),
    ("REJECTED", "Rejected"),
    ("CANCELLED", "Cancelled"),
)

LEAVE_DURATION_CHOICES = (
    ("FULL_DAY", "Full Day"),
    ("FIRST_HALF", "First Half"),
    ("SECOND_HALF", "Second Half"),
)


class LeaveRequest(models.Model):
    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False
    )

    employee = models.ForeignKey(
        empProfile,
        on_delete=models.CASCADE,
        related_name="leave_requests"
    )

    leave_type = models.ForeignKey(
        LeaveTypeMaster,
        on_delete=models.PROTECT,
        related_name="leave_requests"
    )

    start_date = models.DateField()

    end_date = models.DateField()

    number_of_days = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        default=0,
        editable=False
    )

    duration_type = models.CharField(
        max_length=20,
        choices=LEAVE_DURATION_CHOICES,
        default="FULL_DAY"
    )

    reason = models.TextField()

    status = models.CharField(
        max_length=10,
        choices=LEAVE_REQUEST_STATUS_CHOICES,
        default="PENDING"
    )

    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leave_requests_reviewed"
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True
    )

    manager_comment = models.TextField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Leave Request"
        verbose_name_plural = "Leave Requests"
        ordering = ["-created_at"]

    def clean(self):
        super().clean()

        if self.end_date < self.start_date:
            raise ValidationError({
                "end_date": "End date cannot be before start date."
            })

        if (
            self.duration_type in ["FIRST_HALF", "SECOND_HALF"]
            and self.start_date != self.end_date
        ):
            raise ValidationError({
                "duration_type": (
                    "Half-day leave can only be applied for a single date."
                )
            })

        overlapping_requests = LeaveRequest.objects.filter(
            employee=self.employee,
            status__in=["PENDING", "APPROVED"],
            start_date__lte=self.end_date,
            end_date__gte=self.start_date,
        )

        if self.pk:
            overlapping_requests = overlapping_requests.exclude(pk=self.pk)

        if overlapping_requests.exists():
            raise ValidationError(
                "An overlapping pending or approved leave request already exists."
            )

    def calculate_number_of_days(self):
        if self.duration_type in ["FIRST_HALF", "SECOND_HALF"]:
            return Decimal("0.5")

        total_days = (self.end_date - self.start_date).days + 1
        return Decimal(str(total_days))

    def save(self, *args, **kwargs):
        self.number_of_days = self.calculate_number_of_days()
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.employee} — "
            f"{self.leave_type.code} — "
            f"{self.start_date} to {self.end_date}"
        )
    # ── Clearance / NOC Module ─────────────────────────────────────────────



# ── Holiday Calendar Module: Phase 1 ──────────────────────────────────

HOLIDAY_TYPE_CHOICES = (
    ("MANDATORY", "Mandatory"),
    ("OPTIONAL", "Optional"),
)


class Holiday(models.Model):
    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False
    )

    name = models.CharField(
        max_length=150
    )

    date = models.DateField()

    holiday_type = models.CharField(
        max_length=10,
        choices=HOLIDAY_TYPE_CHOICES,
        default="MANDATORY"
    )

    description = models.TextField(
        null=True,
        blank=True
    )

    is_active = models.BooleanField(
        default=True
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="holidays_created"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = ["date"]
        verbose_name = "Holiday"
        verbose_name_plural = "Holidays"

        constraints = [
            models.UniqueConstraint(
                fields=["name", "date"],
                name="unique_holiday_name_per_date"
            )
        ]

    def __str__(self):
        return f"{self.name} - {self.date}"


OPTIONAL_HOLIDAY_REQUEST_STATUS_CHOICES = (
    ("PENDING", "Pending"),
    ("APPROVED", "Approved"),
    ("REJECTED", "Rejected"),
    ("CANCELLED", "Cancelled"),
)


class OptionalHolidayRequest(models.Model):
    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    employee = models.ForeignKey(
        empProfile,
        on_delete=models.CASCADE,
        related_name="optional_holiday_requests",
    )

    holiday = models.ForeignKey(
        Holiday,
        on_delete=models.PROTECT,
        related_name="employee_requests",
    )

    reason = models.TextField(
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=10,
        choices=OPTIONAL_HOLIDAY_REQUEST_STATUS_CHOICES,
        default="PENDING",
    )

    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="optional_holiday_requests_reviewed",
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["-holiday__date"]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "employee",
                    "holiday",
                ],
                name="unique_employee_optional_holiday_request",
            )
        ]

    def clean(self):
        super().clean()

        if (
            self.holiday_id
            and self.holiday.holiday_type != "OPTIONAL"
        ):
            raise ValidationError({
                "holiday":
                    "Only optional holidays can be selected."
            })

    def __str__(self):
        return (
            f"{self.employee} — "
            f"{self.holiday.name} — "
            f"{self.get_status_display()}"
        )


CLEARANCE_REQUEST_TYPE_CHOICES = (
    ("NOC", "NOC / Clearance"),
    ("TERMINATION", "Termination / Exit"),
)


CLEARANCE_REQUEST_STATUS_CHOICES = (
    ("PENDING", "Pending"),
    ("REJECTED", "Rejected"),
    ("READY_FOR_FINALIZATION", "Ready for Finalization"),
    ("COMPLETED", "Completed"),
)


CLEARANCE_APPROVAL_TYPE_CHOICES = (
    ("MANAGER_NOC", "Manager NOC"),
    ("FINANCE_NOC", "Finance NOC"),
)


CLEARANCE_APPROVAL_STATUS_CHOICES = (
    ("PENDING", "Pending"),
    ("APPROVED", "Approved"),
    ("REJECTED", "Rejected"),
)


class ClearanceRequest(models.Model):
    """
    Represents the overall NOC / clearance request for an employee.

    A request may be created:
    - by an employee for themselves
    - by HR on behalf of an employee
    - by HR as part of an employee termination / exit

    Individual manager and finance decisions are stored separately in
    ClearanceApproval.
    """

    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False
    )

    employee = models.ForeignKey(
        empProfile,
        on_delete=models.PROTECT,
        related_name="clearance_requests"
    )

    request_type = models.CharField(
        max_length=20,
        choices=CLEARANCE_REQUEST_TYPE_CHOICES,
        default="NOC"
    )

    requested_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="clearance_requests_created"
    )

    reason = models.TextField()

    status = models.CharField(
        max_length=30,
        choices=CLEARANCE_REQUEST_STATUS_CHOICES,
        default="PENDING"
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True
    )

    finalized_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clearance_requests_finalized"
    )

    finalized_at = models.DateTimeField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        verbose_name = "Clearance Request"
        verbose_name_plural = "Clearance Requests"
        ordering = ["-created_at"]

    def __str__(self):
        employee_name = (
            self.employee.user.get_full_name()
            or self.employee.user.username
        )

        return (
            f"{employee_name} — "
            f"{self.get_request_type_display()} — "
            f"{self.get_status_display()}"
        )


class ClearanceApproval(models.Model):
    """
    Represents one approval step belonging to a ClearanceRequest.

    Initial approval types:
    - MANAGER_NOC
    - FINANCE_NOC
    """

    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False
    )

    clearance_request = models.ForeignKey(
        ClearanceRequest,
        on_delete=models.CASCADE,
        related_name="approvals"
    )

    approval_type = models.CharField(
        max_length=20,
        choices=CLEARANCE_APPROVAL_TYPE_CHOICES
    )

    # Manager NOC will be assigned to the employee's reporting manager.
    # Finance NOC initially remains a shared FINANCE queue.
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clearance_approvals_assigned"
    )

    status = models.CharField(
        max_length=10,
        choices=CLEARANCE_APPROVAL_STATUS_CHOICES,
        default="PENDING"
    )

    decided_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clearance_approvals_decided"
    )

    decided_at = models.DateTimeField(
        null=True,
        blank=True
    )

    remarks = models.TextField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        verbose_name = "Clearance Approval"
        verbose_name_plural = "Clearance Approvals"
        ordering = ["-created_at"]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "clearance_request",
                    "approval_type",
                ],
                name="unique_clearance_approval_type_per_request"
            )
        ]

    def clean(self):
        super().clean()

        if (
            self.approval_type == "MANAGER_NOC"
            and not self.assigned_to
        ):
            raise ValidationError({
                "assigned_to": (
                    "Manager NOC must be assigned "
                    "to the employee's reporting manager."
                )
            })

        if (
            self.status == "REJECTED"
            and not (self.remarks or "").strip()
        ):
            raise ValidationError({
                "remarks": (
                    "Remarks are required when rejecting "
                    "a clearance approval."
                )
            })

    def __str__(self):
        employee = self.clearance_request.employee

        employee_name = (
            employee.user.get_full_name()
            or employee.user.username
        )

        return (
            f"{employee_name} — "
            f"{self.get_approval_type_display()} — "
            f"{self.get_status_display()}"
        )


# ── Employee Exit / Resignation Module ─────────────────────────────────


EMPLOYEE_EXIT_TYPE_CHOICES = (
    ("RESIGNATION", "Resignation"),
    ("TERMINATION", "Termination"),
)


EMPLOYEE_EXIT_STATUS_CHOICES = (
    ("SUBMITTED", "Submitted"),
    ("HR_REJECTED", "HR Rejected"),
    ("CLEARANCE_IN_PROGRESS", "Clearance In Progress"),
    ("CLEARANCE_REJECTED", "Clearance Rejected"),
    ("READY_FOR_FINALIZATION", "Ready for Finalization"),
    ("COMPLETED", "Completed"),
)


class EmployeeExitRequest(models.Model):
    """
    Represents an employee resignation or an HR-initiated termination.

    Resignation flow:
    Employee submits
        -> HR reviews
        -> Clearance starts
        -> Manager + Finance NOC
        -> HR finalizes exit

    Termination flow:
    HR initiates
        -> Clearance starts immediately
        -> Manager + Finance NOC
        -> HR finalizes exit
    """

    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
    )

    employee = models.ForeignKey(
        empProfile,
        on_delete=models.PROTECT,
        related_name="exit_requests",
    )

    exit_type = models.CharField(
        max_length=20,
        choices=EMPLOYEE_EXIT_TYPE_CHOICES,
    )

    initiated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_exit_requests_initiated",
    )

    reason = models.TextField()

    proposed_last_working_date = models.DateField(
        null=True,
        blank=True,
    )

    final_last_working_date = models.DateField(
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=30,
        choices=EMPLOYEE_EXIT_STATUS_CHOICES,
        default="SUBMITTED",
    )

    hr_reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_exit_requests_reviewed",
    )

    hr_reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    hr_remarks = models.TextField(
        null=True,
        blank=True,
    )

    clearance_request = models.OneToOneField(
        ClearanceRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_exit_request",
    )

    # HR user who performed the final exit action.
    finalized_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_exit_requests_finalized",
    )

    # Exact date/time when the exit was finalized.
    finalized_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def clean(self):
        super().clean()

        if not (self.reason or "").strip():
            raise ValidationError(
                {
                    "reason": "A reason is required."
                }
            )

        if (
            self.exit_type == "RESIGNATION"
            and not self.proposed_last_working_date
        ):
            raise ValidationError(
                {
                    "proposed_last_working_date":
                        "Proposed last working date is required "
                        "for a resignation."
                }
            )

    def __str__(self):
        return (
            f"{self.employee} - "
            f"{self.get_exit_type_display()} - "
            f"{self.get_status_display()}"
        )