import uuid
from django.db import models
from .fields import EncryptedCharField, EncryptedDecimalField, EncryptedTextField
from .blind_index import BlindIndexError, aadhaar_index, phone_index
from django.contrib.auth.models import User
from datetime import time
from django.utils import timezone
from decimal import Decimal
from .statutory import get_rule
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
import calendar
import io
from PIL import Image, UnidentifiedImageError
from django.core.files.uploadedfile import InMemoryUploadedFile
from datetime import timedelta, date
from django.conf import settings 
import hashlib, hmac

# class EmailOTP(models.Model):
#     email = models.EmailField(db_index=True)
#     code = models.CharField(max_length=6)
#     created_at = models.DateTimeField(auto_now_add=True)
#     used = models.BooleanField(default=False)

#     def is_valid(self):
#         not_expired = (timezone.now() - self.created_at).seconds < 300  # 5 min
#         return not_expired and not self.used

class EmailOTP(models.Model):
    MAX_ATTEMPTS = 5
    LIFETIME_SECONDS = 300  # 5 min

    email = models.EmailField(db_index=True)
    code = models.CharField(max_length=64)  # HMAC-SHA256 hex digest, never the raw code
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0)

    @staticmethod
    def hash_code(email, code):
        message = f"{email.lower()}:{code}".encode()
        return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()

    def matches(self, code):
        return hmac.compare_digest(self.code, self.hash_code(self.email, code))

    def is_valid(self):
        age = (timezone.now() - self.created_at).total_seconds()
        return (
            age < self.LIFETIME_SECONDS
            and not self.used
            and self.attempts < self.MAX_ATTEMPTS
        )
    

class WhatsAppOTP(models.Model):
    phone_number = models.CharField(max_length=20)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)

    def is_valid(self):
        if self.used:
            return False
        expiry = self.created_at + datetime.timedelta(minutes=5)
        return timezone.now() <= expiry

    def __str__(self):
        return f"{self.phone_number} - {self.code}"
    

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

    organization = models.ForeignKey(
        "app_organizations.Organization",
        on_delete=models.PROTECT,
        related_name="emp_profiles",
        help_text="Organization this employee belongs to.",
    )


    manager = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="team_members",
        help_text="Reporting manager or immediate superior of this employee."
    )

    project = models.ForeignKey(
        "app_projects.Project",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employees",
        help_text="Project (site or city) this employee is assigned to. Blank means unassigned.",
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

    phone_number = EncryptedCharField(max_length=15, null=True, blank=True)

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

    address = EncryptedTextField(null=True, blank=True)

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

    # ── Onboarding / bulk-import fields ─────────────────────────────
    aadhar_no = EncryptedCharField(
        max_length=20,
        null=True,
        blank=True,
        help_text="12-digit Aadhar number."
    )

    pan_no = EncryptedCharField(
        max_length=10,
        null=True,
        blank=True,
        help_text="PAN number, e.g. ABCDE1234F."
    )

    bank_name = models.CharField(
        max_length=100,
        null=True,
        blank=True
    )

    bank_account_no = EncryptedCharField(max_length=30, null=True, blank=True)

    ifsc_no = models.CharField(
        max_length=15,
        null=True,
        blank=True
    )

    uan_no = EncryptedCharField(
        max_length=20,
        null=True,
        blank=True,
        help_text="Universal Account Number (EPFO)."
    )

    esic_no = EncryptedCharField(max_length=20, null=True, blank=True)

    avsec_training_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date of AVSEC training completion."
    )

    police_verification_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date of police verification."
    )


    # Blind-index fingerprints (keyed hash; see appEmp/blind_index.py).
    aadhar_bidx = models.CharField(max_length=64, null=True, blank=True, unique=True, editable=False)
    phone_bidx = models.CharField(max_length=64, null=True, blank=True, db_index=True, editable=False)

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

    def _refresh_fingerprints(self, update_fields=None):
        """
        Recompute the blind-index fingerprints from the current values.
        With update_fields, only the fingerprints whose source field is listed
        are recomputed. Returns the fingerprint field names that were set.
        """
        changed = []
        if update_fields is None or "aadhar_no" in update_fields:
            try:
                self.aadhar_bidx = aadhaar_index(self.aadhar_no)
            except BlindIndexError:
                raise ValidationError({
                    "aadhar_no": "Enter a valid 12-digit Aadhaar number."
                }) from None
            changed.append("aadhar_bidx")
        if update_fields is None or "phone_number" in update_fields:
            self.phone_bidx = phone_index(self.phone_number)
            changed.append("phone_bidx")
        return changed

    def clean(self):
        """
        Prevent an employee from being assigned as their own manager.
        """
        super().clean()

        if self.manager_id and self.manager_id == self.pk:
            raise ValidationError({
                "manager": "An employee cannot be their own manager."
            })

        self._refresh_fingerprints()

        if self.aadhar_bidx:
            clash = empProfile.objects.filter(aadhar_bidx=self.aadhar_bidx).exclude(pk=self.pk)
            if clash.exists():
                raise ValidationError(
                    "This Aadhaar number is already registered. "
                    "Check the number. If it is correct, contact support."
                )

    def save(self, *args, **kwargs):
        """
        Ensure only one employee is marked as the default manager.
        """
        update_fields_arg = kwargs.get("update_fields")
        if self.project_id and (
            update_fields_arg is None
            or {"project", "project_id"} & set(update_fields_arg)
        ):
            if self.project.organization_id != self.organization_id:
                raise ValidationError(
                    "The project belongs to a different organization."
                )

        update_fields = kwargs.get("update_fields")
        changed = self._refresh_fingerprints(update_fields)
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | set(changed)

        if self.is_default_manager:
            empProfile.objects.filter(
                organization=self.organization,
                is_default_manager=True
            ).exclude(
                pk=self.pk
            ).update(
                is_default_manager=False
            )

        if not self.work_schedule_id:
            default_schedule = WorkSchedule.objects.filter(
                organization=self.organization,
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
    check_in_latitude = models.FloatField(null=True, blank=True)
    check_in_longitude = models.FloatField(null=True, blank=True)
    check_out = models.DateTimeField(null=True, blank=True)
    check_out_latitude = models.FloatField(null=True, blank=True)
    check_out_longitude = models.FloatField(null=True, blank=True)
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


# class Salary(models.Model):
#     """
#     One row per salary revision. Only one row per employee has is_active=True
#     at any time — that's the 'current' salary. Keeping history instead of
#     overwriting means you can later show raise history / generate slips for
#     past months using the salary that was active then, if you want.
#     """
#     uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
#     employee = models.ForeignKey(
#         empProfile,
#         on_delete=models.CASCADE,
#         related_name='salary_records',
#     )
#     basic_salary = models.DecimalField(max_digits=12, decimal_places=2)
#     hra = models.DecimalField(max_digits=12, decimal_places=2, default=0)
#     pf = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # employee contribution — deducted, not added

#     effective_date = models.DateField(default=timezone.now)
#     is_active = models.BooleanField(default=True)

#     created_by = models.ForeignKey(
#         User,
#         null=True, blank=True,
#         on_delete=models.SET_NULL,
#         related_name='salaries_created',
#     )
#     created_at = models.DateTimeField(auto_now_add=True)
#     updated_at = models.DateTimeField(auto_now=True)

#     class Meta:
#         ordering = ['-effective_date', '-created_at']

#     def __str__(self):
#         return f"{self.employee.user.get_full_name() or self.employee.user.username} — {self.effective_date}"

#     def save(self, *args, **kwargs):
#         # Enforce "only one active record per employee" at save time.
#         if self.is_active:
#             Salary.objects.filter(
#                 employee=self.employee, is_active=True
#             ).exclude(pk=self.pk).update(is_active=False)
#         super().save(*args, **kwargs)

#     # ── Derived figures ────────────────────────────────────────────────
#     @property
#     def gross_monthly(self):
#         return self.basic_salary + self.hra

#     @property
#     def ctc_monthly(self):
#         """CTC = Basic + HRA only. PF is an employee deduction, NOT added to CTC."""
#         return self.basic_salary + self.hra

#     @property
#     def ctc_annual(self):
#         return self.ctc_monthly * 12

#     def calculate_annual_tax(self):
#         """
#         SIMPLIFIED illustrative slab calc (India, new-regime-style slabs) +
#         4% health & education cess, applied on annual gross (Basic + HRA).
#         This is NOT a substitute for a real payroll/tax engine — confirm
#         actual slabs and exemptions with your finance team before this
#         feeds real payslips.
#         """
#         annual_taxable = self.gross_monthly * 12
#         if annual_taxable < 0:
#             annual_taxable = Decimal('0')

#         slabs = [
#             (Decimal('300000'), Decimal('0.00')),
#             (Decimal('600000'), Decimal('0.05')),
#             (Decimal('900000'), Decimal('0.10')),
#             (Decimal('1200000'), Decimal('0.15')),
#             (Decimal('1500000'), Decimal('0.20')),
#             (Decimal('Infinity'), Decimal('0.30')),
#         ]

#         tax = Decimal('0')
#         lower = Decimal('0')
#         for upper, rate in slabs:
#             if annual_taxable > lower:
#                 taxable_in_band = min(annual_taxable, upper) - lower
#                 tax += taxable_in_band * rate
#                 lower = upper
#             else:
#                 break

#         tax += tax * Decimal('0.04')  # cess
#         return tax.quantize(Decimal('0.01'))

#     def calculate_monthly_tds(self):
#         return (self.calculate_annual_tax() / Decimal('12')).quantize(Decimal('0.01'))

#     @property
#     def net_monthly_pay(self):
#         """Net Pay = Gross (Basic + HRA) minus PF (employee contribution) minus TDS."""
#         return self.gross_monthly - self.pf - self.calculate_monthly_tds()

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
    organization = models.ForeignKey(
        "app_organizations.Organization",
        on_delete=models.PROTECT,
        editable=False,
        related_name="salaries",
    )
    basic_salary = EncryptedDecimalField(max_digits=12, decimal_places=2)
    hra = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    da = EncryptedDecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Dearness allowance (monthly). Counts as wages for PF.",
    )
    special_allowance = EncryptedDecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Balancing allowance (monthly). Not counted as wages unless the 50% rule applies.",
    )
    other_allowances = EncryptedDecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Any other fixed monthly allowance.",
    )
    use_statutory_wages = models.BooleanField(
        default=False,
        help_text="Calculate PF on statutory wages (Basic + DA, at least 50% of pay) instead of full pay.",
    )
    pf = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)  # employee contribution, deducted not added
    esi = EncryptedDecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Monthly ESI employee contribution (deducted, not added to CTC).",
    )
    other_deductions = EncryptedDecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Any other fixed monthly deduction (advances, professional tax, etc.).",
    )

    # ── Wage-basis fields (for daily-wage register support) ────────────
    WAGE_TYPE_CHOICES = (
        ('MONTHLY', 'Monthly / CTC'),
        ('DAILY', 'Daily Wage'),
    )
    wage_type = models.CharField(
        max_length=10,
        choices=WAGE_TYPE_CHOICES,
        default='MONTHLY',
        help_text="MONTHLY = existing CTC/TDS flow. DAILY = wage-register (Bonus/EPF/ESIC) flow.",
    )
    daily_rate = EncryptedDecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Only used when wage_type=DAILY. If blank, derived from basic_salary / days in month.",
    )
    # ─────────────────────────────────────────────────────────────────


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
        self.organization_id = self.employee.organization_id
        # Enforce "only one active record per employee" at save time.
        if self.is_active:
            Salary.objects.filter(
                employee=self.employee, is_active=True
            ).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    # ── Derived figures ────────────────────────────────────────────────
    @property
    def gross_monthly(self):
        return (
            self.basic_salary + self.hra + self.da
            + self.special_allowance + self.other_allowances
        )

    @property
    def ctc_monthly(self):
        """Gross pay of all components. Employer PF/ESI are not added here."""
        return self.gross_monthly

    @property
    def ctc_annual(self):
        return self.ctc_monthly * 12

    # ── Daily-rate helper for the wage register ─────────────────────────
    def get_daily_rate(self, days_in_month):
        """
        Returns the per-day wage rate to use for wage-register calculations.
        - If wage_type=DAILY and daily_rate is set, use it directly.
        - Otherwise, derive it from basic_salary spread across days_in_month.
        """
        if self.wage_type == 'DAILY' and self.daily_rate:
            return self.daily_rate
        if days_in_month <= 0:
            raise ValidationError("days_in_month must be positive to derive a daily rate.")
        return (self.basic_salary / Decimal(days_in_month)).quantize(Decimal('0.01'))
    # ─────────────────────────────────────────────────────────────────

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
        """Estimated monthly TDS on a full year of this salary (see appEmp/tds.py)."""
        from .tds import estimate_monthly_tds
        return estimate_monthly_tds(self)

    @property
    def fixed_deductions_monthly(self):
        """PF + ESI + other fixed deductions (everything except TDS)."""
        return self.pf + self.esi + self.other_deductions

    @property
    def total_deductions_monthly(self):
        return self.fixed_deductions_monthly + self.calculate_monthly_tds()

    @property
    def net_monthly_pay(self):
        """Net Pay = Gross (Basic + HRA) minus PF, ESI, other deductions and TDS."""
        return self.gross_monthly - self.total_deductions_monthly


class WageRegisterEntry(models.Model):
    """
    One row per employee per wage-month. Consumes Salary for rate/wage-type,
    Attendance for days worked and OT, Holiday for national holidays.
    All formula columns (H–R in the source register) are @property methods —
    never stored, always computed live from the fields below.
    """
    OT_UNIT_CHOICES = (('HOURS', 'Hours'), ('DAYS', 'Day-equivalent'))

    BONUS_WAGE_CEILING = Decimal('21000')

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    salary = models.ForeignKey(Salary, on_delete=models.PROTECT, related_name='wage_entries')
    organization = models.ForeignKey(
        "app_organizations.Organization",
        on_delete=models.PROTECT,
        editable=False,
        related_name="wage_register_entries",
    )
    wage_month = models.DateField(help_text="Any date within the wage month; day is ignored.")

    # ── Rate override ────────────────────────────────────────────────

    rate_override = EncryptedDecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Leave blank to use Salary.get_daily_rate(). Set to override for this month only."
    )

    # ── Form entry ──────────────────────────────────────────────────
    national_holidays_in_month = models.PositiveSmallIntegerField(
        default=0, help_text="Pre-fill from Holiday model; editable."
    )

    days_worked_override = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)

    ot_hours_override = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        help_text="Leave blank to auto-calculate from Attendance vs Shift hours."
    )

    # Mode of payment / date — set later via mark_as_paid(), not at creation
    mode_of_payment = models.CharField(max_length=100, blank=True)
    payment_date = models.DateField(null=True, blank=True)

    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('salary', 'wage_month')
        ordering = ['-wage_month']

    def save(self, *args, **kwargs):
        self.organization_id = self.salary.organization_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.salary.employee} — {self.wage_month:%b %Y}"

    # ── Month boundaries ─────────────────────────────────────────────
    @property
    def month_start(self):
        return self.wage_month.replace(day=1)

    @property
    def month_end(self):
        next_month = (self.month_start + timedelta(days=32)).replace(day=1)
        return next_month - timedelta(days=1)

    @property
    def days_in_month(self):
        return self.month_end.day

    # ── Days worked (auto from Attendance, override allowed) ───────────
    def compute_days_worked(self):
        return Attendance.objects.filter(
            employee=self.salary.employee,
            date__gte=self.month_start, date__lte=self.month_end,
            status='PRESENT',
        ).count()

    @property
    def days_worked(self):
        if self.days_worked_override is not None:
            return self.days_worked_override
        return Decimal(self.compute_days_worked())

    # ── OT (auto from Attendance vs Shift, override allowed) ───────────
    def compute_ot_hours(self):
        employee = self.salary.employee
        shift = employee.shift
        if not shift:
            return Decimal('0')

        start_dt = shift.start_time
        end_dt = shift.end_time
        expected_seconds = (
            (24 * 3600 - (start_dt.hour * 3600 + start_dt.minute * 60) + (end_dt.hour * 3600 + end_dt.minute * 60))
            if shift.is_night_shift else
            ((end_dt.hour * 3600 + end_dt.minute * 60) - (start_dt.hour * 3600 + start_dt.minute * 60))
        )
        if expected_seconds <= 0:
            return Decimal('0')
        expected_hours = Decimal(expected_seconds) / Decimal(3600)

        total_ot = Decimal('0')
        records = Attendance.objects.filter(
            employee=employee,
            date__gte=self.month_start, date__lte=self.month_end,
            status='PRESENT',
            check_in__isnull=False, check_out__isnull=False,
        )
        for rec in records:
            worked_hours = Decimal((rec.check_out - rec.check_in).total_seconds()) / Decimal(3600)
            if worked_hours > expected_hours:
                total_ot += (worked_hours - expected_hours)
        return total_ot.quantize(Decimal('0.01'))

    @property
    def operational_ot_hours(self):
        if self.ot_hours_override is not None:
            return self.ot_hours_override
        return self.compute_ot_hours()

    @property
    def ot_hours_per_day(self):
        shift = self.salary.employee.shift
        if not shift:
            return Decimal('8.00')
        start_dt, end_dt = shift.start_time, shift.end_time
        seconds = (
            (24 * 3600 - (start_dt.hour * 3600 + start_dt.minute * 60) + (end_dt.hour * 3600 + end_dt.minute * 60))
            if shift.is_night_shift else
            ((end_dt.hour * 3600 + end_dt.minute * 60) - (start_dt.hour * 3600 + start_dt.minute * 60))
        )
        return (Decimal(seconds) / Decimal(3600)) if seconds > 0 else Decimal('8.00')

    @property
    def ot_in_days(self):
        return self.operational_ot_hours / self.ot_hours_per_day

    # ── Rate ────────────────────────────────────────────────────────
    @property
    def rate_of_wages(self):
        if self.rate_override is not None:
            return self.rate_override
        return self.salary.get_daily_rate(self.days_in_month)

    # ── Register columns (formula names match your sheet) ─────────────
    @property
    def total_operational_ot(self):          # D×G = H
        return (self.rate_of_wages * self.ot_in_days).quantize(Decimal('0.01'))

    @property
    def national_holiday_wage(self):          # D×NH = I
        return (self.rate_of_wages * self.national_holidays_in_month).quantize(Decimal('0.01'))

    @property
    def total_days(self):                     # NH+F+G = J
        return self.national_holidays_in_month + self.days_worked + self.ot_in_days

    @property
    def total_wages_workday(self):            # D×F = K
        return (self.rate_of_wages * self.days_worked).quantize(Decimal('0.01'))

    @property
    def total_wages_workday_nh(self):         # D×J = L
        return (self.rate_of_wages * self.total_days).quantize(Decimal('0.01'))

    @property
    def bonus(self):                          # 8.33% on capped ₹21,000, pro-rated by days worked
        capped_monthly = min(self.rate_of_wages * self.days_in_month, self.BONUS_WAGE_CEILING)
        pro_rated = capped_monthly * (self.days_worked / Decimal(self.days_in_month))
        return (pro_rated * Decimal('0.0833')).quantize(Decimal('0.01'))

    @property
    def gross_total(self):                    # L+M = N
        return self.total_wages_workday_nh + self.bonus

    def _rule(self, key):
        cache = self.__dict__.setdefault('_rule_cache', {})
        if key not in cache:
            cache[key] = get_rule(key, self.month_start)
        return cache[key]

    @property
    def epf_wage_ceiling(self):
        return self._rule('EPF_WAGE_CEILING')

    @property
    def epf_wage_base(self):
        return min(self.total_wages_workday, self.epf_wage_ceiling)

    @property
    def epf_employee(self):                   # min(K,15000)×12% = O
        return (self.epf_wage_base * self._rule('EPF_EMPLOYEE_RATE')).quantize(Decimal('0.01'))

    @property
    def epf_employer(self):                   # min(K,15000)×13% — display only, not deducted
        employer_rate = (
            self._rule('EPF_EMPLOYER_EPS_RATE')
            + self._rule('EPF_EMPLOYER_EPF_RATE')
            + self._rule('EDLI_RATE')
            + self._rule('EPF_ADMIN_RATE')
        )
        return (self.epf_wage_base * employer_rate).quantize(Decimal('0.01'))

    @property
    def esic_wage_base(self):
        if self.total_wages_workday > self._rule('ESIC_WAGE_CEILING'):
            return Decimal('0.00')
        return self.total_wages_workday

    @property
    def esic(self):                           # min(K,21000)×0.75% = P
        return (self.esic_wage_base * self._rule('ESIC_EMPLOYEE_RATE')).quantize(Decimal('0.01'))

    @property
    def total_deduction(self):                # O+P = Q
        return self.epf_employee + self.esic

    @property
    def net_payment(self):                    # N-Q = R
        return self.gross_total - self.total_deduction

    # ── Mark paid (system-updates mode/date, per your sheet) ───────────
    def mark_as_paid(self, mode, paid_on=None):
        self.mode_of_payment = mode
        self.payment_date = paid_on or date.today()
        self.save(update_fields=['mode_of_payment', 'payment_date', 'updated_at'])


class PayrollRecord(models.Model):
    """
    Frozen monthly payroll snapshot for MONTHLY-wage employees (DAILY-wage staff
    stay on WageRegisterEntry).

    Why stored instead of derived: once HR locks a month, the figures on the
    payslip must never change, even if attendance is edited later or the
    salary is revised. Every amount and day-count is therefore a snapshot.
    Amounts are encrypted like Salary; sum them in Python, not in the database.
    """
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    organization = models.ForeignKey(
        "app_organizations.Organization",
        on_delete=models.PROTECT,
        editable=False,
        related_name="payroll_records",
    )
    employee = models.ForeignKey(
        empProfile, on_delete=models.PROTECT, related_name="payroll_records",
    )
    salary = models.ForeignKey(
        Salary, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="payroll_records",
        help_text="The salary revision that was active when this record was generated.",
    )
    year = models.PositiveIntegerField()
    month = models.PositiveSmallIntegerField()  # 1-12
    period_start = models.DateField()
    period_end = models.DateField()

    # ── Day breakdown (snapshot) ───────────────────────────────────────
    days_in_period = models.PositiveSmallIntegerField()
    working_days = models.PositiveSmallIntegerField(default=0)
    present_days = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    paid_leave_days = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    holiday_days = models.PositiveSmallIntegerField(default=0)
    weekly_off_days = models.PositiveSmallIntegerField(default=0)
    unpaid_leave_days = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    absent_days = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    lop_days = models.DecimalField(
        max_digits=5, decimal_places=1, default=0,
        help_text="Loss-of-pay days = unpaid leave + absent (+ half-day shortfalls).",
    )
    payable_days = models.DecimalField(max_digits=5, decimal_places=1, default=0)

    # ── Money (snapshot, encrypted) ────────────────────────────────────
    basic_salary = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    hra = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    gross_monthly = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    gross_earned = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    pf = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    esi = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    other_deductions = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    tds = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    professional_tax = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    total_deductions = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    net_pay = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)

    # ── Employer share and wage bases (snapshot, not deducted) ─────────
    pf_wage_base = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    esi_wage_base = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    employer_eps = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    employer_epf = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    employer_edli = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    employer_pf_admin = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    employer_esi = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)

    # ── Salary components and statutory wages (snapshot) ───────────────
    da = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    special_allowance = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    other_allowances = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    statutory_wages = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)

    # ── Deduction cap (snapshot) ───────────────────────────────────────
    deferred_deductions = EncryptedDecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Other deductions not taken this month because total deductions are capped."
    )

    # ── Lock state ─────────────────────────────────────────────────────
    is_locked = models.BooleanField(default=False)
    locked_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="payroll_records_locked",
    )
    locked_at = models.DateTimeField(null=True, blank=True)

    mode_of_payment = models.CharField(max_length=100, blank=True)
    payment_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    LOCK_FIELDS = {
        "is_locked", "locked_by", "locked_at",
        "mode_of_payment", "payment_date", "updated_at",
    }

    class Meta:
        ordering = ["-year", "-month", "employee__user__first_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "year", "month"],
                name="unique_payroll_record_per_employee_month",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "year", "month"]),
        ]

    def __str__(self):
        return f"{self.employee} - {self.year}-{self.month:02d}"

    def save(self, *args, **kwargs):
        self.organization_id = self.employee.organization_id
        # A locked record is a legal/financial snapshot: only lock-state and
        # payment fields may change on it. Unlock first to recalculate.
        if self.pk:
            persisted_locked = PayrollRecord.objects.filter(
                pk=self.pk, is_locked=True
            ).exists()
            if persisted_locked:
                update_fields = kwargs.get("update_fields")
                if not update_fields or not set(update_fields) <= self.LOCK_FIELDS:
                    raise ValidationError(
                        "This payroll record is locked. Unlock it before changing it."
                    )
        super().save(*args, **kwargs)

    def lock(self, user):
        self.is_locked = True
        self.locked_by = user
        self.locked_at = timezone.now()
        self.save(update_fields=["is_locked", "locked_by", "locked_at", "updated_at"])

    def unlock(self):
        self.is_locked = False
        self.locked_by = None
        self.locked_at = None
        self.save(update_fields=["is_locked", "locked_by", "locked_at", "updated_at"])

    def delete(self, *args, **kwargs):
        if self.is_locked:
            raise ValidationError("A locked payroll record cannot be deleted.")
        return super().delete(*args, **kwargs)

    @property
    def period_label(self):
        return date(self.year, self.month, 1).strftime("%B %Y")

    @property
    def employer_contribution_total(self):
        return (
            self.employer_eps + self.employer_epf + self.employer_edli
            + self.employer_pf_admin + self.employer_esi
        )


class StatutoryRule(models.Model):
    """
    A government-set rate or ceiling that applies to every organization.
    Looked up by key and date (see appEmp/statutory.py), never hardcoded.
    Rates are stored as fractions: 0.12 means 12%.
    Edited by superusers only (Django admin).
    """
    KEY_LABELS = {
        'EPF_WAGE_CEILING': 'EPF wage ceiling (monthly, Rs)',
        'EPF_EMPLOYEE_RATE': 'EPF employee rate',
        'EPF_EMPLOYER_EPS_RATE': 'EPF employer share to EPS',
        'EPF_EMPLOYER_EPF_RATE': 'EPF employer share to EPF',
        'EDLI_RATE': 'EDLI employer rate',
        'EPF_ADMIN_RATE': 'EPF admin charges rate',
        'ESIC_WAGE_CEILING': 'ESIC wage ceiling (monthly, Rs)',
        'ESIC_EMPLOYEE_RATE': 'ESIC employee rate',
        'ESIC_EMPLOYER_RATE': 'ESIC employer rate',
        'ESIC_DAILY_WAGE_EXEMPTION': 'ESIC daily wage below which employee share is exempt (Rs)',
        'WAGES_MIN_SHARE': 'Minimum share of total pay counted as wages (50% rule)',
        'TAX_STD_DEDUCTION_NEW': 'Standard deduction, new regime (yearly, Rs)',
        'TAX_STD_DEDUCTION_OLD': 'Standard deduction, old regime (yearly, Rs)',
        'TAX_REBATE_LIMIT_NEW': 'Rebate limit, new regime (taxable income, Rs)',
        'TAX_REBATE_MAX_NEW': 'Maximum rebate, new regime (Rs)',
        'TAX_REBATE_LIMIT_OLD': 'Rebate limit, old regime (taxable income, Rs)',
        'TAX_REBATE_MAX_OLD': 'Maximum rebate, old regime (Rs)',
        'TAX_CESS_RATE': 'Health and education cess rate on income tax',
        'TAX_SURCHARGE_FROM': 'Taxable income above which surcharge applies (yearly, Rs)',
        'DEDUCTION_CAP_SHARE': 'Maximum share of earned pay that total deductions may take (50% cap)',
    }

    key = models.CharField(
        max_length=40,
        db_index=True,
        help_text="Rule name, for example EPF_WAGE_CEILING."
    )
    value = models.DecimalField(max_digits=12, decimal_places=4)
    effective_from = models.DateField()
    effective_to = models.DateField(
        null=True,
        blank=True,
        help_text="Last day this value applies. Leave blank if it is still in force."
    )
    note = models.CharField(
        max_length=255,
        blank=True,
        help_text="Source or notification reference."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['key', '-effective_from']
        constraints = [
            models.UniqueConstraint(
                fields=['key', 'effective_from'],
                name='uniq_statutory_rule_key_from',
            ),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gte=models.F('effective_from')),
                name='statutory_rule_to_after_from',
            ),
        ]

    def clean(self):
        if self.key not in self.KEY_LABELS:
            raise ValidationError({'key': 'Unknown rule key.'})
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValidationError({'effective_to': 'Must be on or after the start date.'})
        if self.effective_from:
            my_end = self.effective_to or date.max
            for other in StatutoryRule.objects.filter(key=self.key).exclude(pk=self.pk):
                other_end = other.effective_to or date.max
                if self.effective_from <= other_end and other.effective_from <= my_end:
                    raise ValidationError(
                        'These dates overlap another rule with the same key.'
                    )

    def __str__(self):
        end = self.effective_to or 'open'
        return f"{self.key} = {self.value} ({self.effective_from} to {end})"


class ProfessionalTaxSlab(models.Model):
    """
    One professional tax slab of one state, monthly pay in rupees.

    A slab matches when above < pay <= up_to (up_to blank = no upper limit).
    month blank = every month; a month-specific slab (for example February)
    wins over an every-month slab whenever both match.
    gender A = everyone, M = men, F = women; a state that has any M or F slab
    needs the employee's gender (see appEmp/professional_tax.py).
    Edited by superusers only (Django admin).
    """
    GENDER_CHOICES = (
        ('A', 'Everyone'),
        ('M', 'Men'),
        ('F', 'Women'),
    )

    state = models.CharField(max_length=40, db_index=True)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, default='A')
    above = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Monthly pay must be more than this (this amount itself is not included)."
    )
    up_to = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Monthly pay up to and including this amount. Leave blank for no upper limit."
    )
    month = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Calendar month 1-12 if this slab applies to one month only. Leave blank for every month."
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    effective_from = models.DateField()
    effective_to = models.DateField(
        null=True, blank=True,
        help_text="Last day this slab applies. Leave blank if it is still in force."
    )
    note = models.CharField(
        max_length=255, blank=True,
        help_text="Source or notification reference."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['state', 'gender', 'above', 'month']
        indexes = [models.Index(fields=['state', 'effective_from'])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gte=0),
                name='pt_slab_amount_not_negative',
            ),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gte=models.F('effective_from')),
                name='pt_slab_to_after_from',
            ),
        ]

    def clean(self):
        if self.month is not None and not 1 <= self.month <= 12:
            raise ValidationError({'month': 'Month must be between 1 and 12.'})
        if self.up_to is not None and self.above is not None and self.up_to <= self.above:
            raise ValidationError({'up_to': 'Must be more than the "above" amount.'})
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValidationError({'effective_to': 'Must be on or after the start date.'})

    def __str__(self):
        top = self.up_to if self.up_to is not None else 'no limit'
        when = f"month {self.month}" if self.month else "every month"
        return f"{self.state} {self.gender}: {self.above} to {top}, {when} = {self.amount}"


class PayrollAuditLog(models.Model):
    """
    Append-only history of payroll locks and unlocks. Entries can never be
    changed or deleted (not even from Django admin). Each entry keeps the
    figures of the record at that moment, so a later change can be traced.
    """
    ACTION_LOCKED = "LOCKED"
    ACTION_UNLOCKED = "UNLOCKED"
    ACTION_EXPORTED = "EXPORTED"
    ACTION_CHOICES = (
        (ACTION_LOCKED, "Locked"),
        (ACTION_UNLOCKED, "Unlocked"),
        (ACTION_EXPORTED, "Exported"),
    )

    organization = models.ForeignKey(
        "app_organizations.Organization",
        on_delete=models.PROTECT,
        editable=False,
        related_name="payroll_audit_logs",
    )
    employee = models.ForeignKey(
        empProfile, on_delete=models.PROTECT, related_name="payroll_audit_logs",
    )
    record = models.ForeignKey(
        PayrollRecord, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    year = models.PositiveIntegerField()
    month = models.PositiveSmallIntegerField()
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="payroll_audit_entries",
    )
    user_name = models.CharField(max_length=150, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    net_pay = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    total_deductions = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    tds = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["employee", "year", "month"]),
            models.Index(fields=["organization", "year", "month"]),
        ]

    def __str__(self):
        return f"{self.action} {self.employee} {self.year}-{self.month:02d}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Payroll audit entries cannot be changed.")
        self.organization_id = self.employee.organization_id
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Payroll audit entries cannot be deleted.")

    @classmethod
    def record_event(cls, record, action, user=None, reason=""):
        """Write one entry for a payroll record, with its figures at this moment."""
        has_user = user is not None and getattr(user, "pk", None)
        return cls.objects.create(
            employee=record.employee,
            record=record,
            year=record.year,
            month=record.month,
            action=action,
            user=user if has_user else None,
            user_name=user.get_username() if has_user else "",
            reason=reason,
            net_pay=record.net_pay,
            total_deductions=record.total_deductions,
            tds=record.tds,
        )


class FinalSettlement(models.Model):
    """
    Full and final settlement of one employee exit. Items are added by HR while
    the settlement is a draft; approving it freezes them. The final month's
    salary is paid through payroll and is NOT an item here (shown as a
    reference only), so it can never be paid twice.
    """
    STATUS_DRAFT = "DRAFT"
    STATUS_APPROVED = "APPROVED"
    STATUS_PAID = "PAID"
    STATUS_CHOICES = (
        (STATUS_DRAFT, "Draft"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_PAID, "Paid"),
    )

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    organization = models.ForeignKey(
        "app_organizations.Organization",
        on_delete=models.PROTECT,
        editable=False,
        related_name="final_settlements",
    )
    exit_request = models.OneToOneField(
        "EmployeeExitRequest", on_delete=models.PROTECT, related_name="settlement",
    )
    employee = models.ForeignKey(
        empProfile, on_delete=models.PROTECT, related_name="final_settlements",
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    approved_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="settlements_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organization", "status"])]

    def __str__(self):
        return f"Settlement: {self.employee} ({self.status})"

    def save(self, *args, **kwargs):
        self.organization_id = self.employee.organization_id
        super().save(*args, **kwargs)

    @property
    def total_earnings(self):
        return sum(
            (i.amount for i in self.items.all() if i.kind == FinalSettlementItem.KIND_EARNING),
            Decimal("0"),
        )

    @property
    def total_deductions(self):
        return sum(
            (i.amount for i in self.items.all() if i.kind == FinalSettlementItem.KIND_DEDUCTION),
            Decimal("0"),
        )

    @property
    def net_payable(self):
        return self.total_earnings - self.total_deductions

    def approve(self, user):
        self.status = self.STATUS_APPROVED
        self.approved_by = user
        self.approved_at = timezone.now()
        self.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])

    def unlock(self):
        self.status = self.STATUS_DRAFT
        self.approved_by = None
        self.approved_at = None
        self.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])

    def mark_paid(self):
        self.status = self.STATUS_PAID
        self.paid_at = timezone.now()
        self.save(update_fields=["status", "paid_at", "updated_at"])


class FinalSettlementItem(models.Model):
    """One earning or deduction line of a final settlement (draft only)."""
    KIND_EARNING = "EARNING"
    KIND_DEDUCTION = "DEDUCTION"
    KIND_CHOICES = (
        (KIND_EARNING, "Earning"),
        (KIND_DEDUCTION, "Deduction"),
    )

    settlement = models.ForeignKey(
        FinalSettlement, on_delete=models.CASCADE, related_name="items",
    )
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    label = models.CharField(max_length=100)
    amount = EncryptedDecimalField(max_digits=12, decimal_places=2)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.kind} {self.label}"

    def save(self, *args, **kwargs):
        if self.settlement.status != FinalSettlement.STATUS_DRAFT:
            raise ValidationError("Items can only be changed while the settlement is a draft.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.settlement.status != FinalSettlement.STATUS_DRAFT:
            raise ValidationError("Items can only be changed while the settlement is a draft.")
        return super().delete(*args, **kwargs)


class FinalSettlementLog(models.Model):
    """Append-only history of a final settlement (create, approve, unlock, paid)."""
    ACTION_CREATED = "CREATED"
    ACTION_APPROVED = "APPROVED"
    ACTION_UNLOCKED = "UNLOCKED"
    ACTION_PAID = "PAID"
    ACTION_CHOICES = (
        (ACTION_CREATED, "Created"),
        (ACTION_APPROVED, "Approved"),
        (ACTION_UNLOCKED, "Unlocked"),
        (ACTION_PAID, "Marked paid"),
    )

    settlement = models.ForeignKey(
        FinalSettlement, on_delete=models.PROTECT, related_name="logs",
    )
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="settlement_log_entries",
    )
    user_name = models.CharField(max_length=150, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    net_payable = EncryptedDecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.action} {self.settlement}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Settlement log entries cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Settlement log entries cannot be deleted.")

    @classmethod
    def record_event(cls, settlement, action, user=None, reason=""):
        has_user = user is not None and getattr(user, "pk", None)
        return cls.objects.create(
            settlement=settlement,
            action=action,
            user=user if has_user else None,
            user_name=user.get_username() if has_user else "",
            reason=reason,
            net_payable=settlement.net_payable,
        )


class IncomeTaxSlab(models.Model):
    """
    One income tax slab (yearly taxable income, rupees) of one tax regime.
    A slab covers above < income <= up_to (up_to blank = no upper limit).
    rate is a fraction: 0.05 means 5%.
    Standard deduction, rebate and cess are StatutoryRule keys (TAX_...).
    Used for TDS on salary (see appEmp/tds.py). Edited by superusers only.
    """
    REGIME_CHOICES = (
        ('NEW', 'New regime'),
        ('OLD', 'Old regime'),
    )

    regime = models.CharField(max_length=3, choices=REGIME_CHOICES, db_index=True)
    above = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Yearly taxable income must be more than this."
    )
    up_to = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        help_text="Up to and including this amount. Leave blank for no upper limit."
    )
    rate = models.DecimalField(
        max_digits=6, decimal_places=4,
        help_text="As a fraction: 0.05 means 5%."
    )
    effective_from = models.DateField()
    effective_to = models.DateField(
        null=True, blank=True,
        help_text="Last day this slab applies. Leave blank if it is still in force."
    )
    note = models.CharField(
        max_length=255, blank=True,
        help_text="Source or notification reference."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['regime', '-effective_from', 'above']
        indexes = [models.Index(fields=['regime', 'effective_from'])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rate__gte=0) & models.Q(rate__lte=1),
                name='it_slab_rate_is_a_fraction',
            ),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gte=models.F('effective_from')),
                name='it_slab_to_after_from',
            ),
        ]

    def clean(self):
        if self.up_to is not None and self.above is not None and self.up_to <= self.above:
            raise ValidationError({'up_to': 'Must be more than the "above" amount.'})
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValidationError({'effective_to': 'Must be on or after the start date.'})

    def __str__(self):
        top = self.up_to if self.up_to is not None else 'no limit'
        return f"{self.regime}: {self.above} to {top} at {self.rate}"


class EmployeeStatutoryProfile(models.Model):
    """
    Per-employee PF, ESI and tax settings.
    PF and ESI amounts can be calculated automatically, kept as the fixed
    amounts typed on Salary, or switched off for this employee.
    UAN, ESIC number and PAN stay on empProfile.
    An employee with no profile row is treated as FIXED.
    """
    MODE_AUTO = 'AUTO'
    MODE_FIXED = 'FIXED'
    MODE_NA = 'NA'
    MODE_CHOICES = (
        (MODE_AUTO, 'Auto-calculate'),
        (MODE_FIXED, 'Fixed amount'),
        (MODE_NA, 'Not applicable'),
    )
    REGIME_CHOICES = (
        ('NEW', 'New regime'),
        ('OLD', 'Old regime'),
    )

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    employee = models.OneToOneField(
        empProfile,
        on_delete=models.CASCADE,
        related_name='statutory_profile',
    )
    organization = models.ForeignKey(
        "app_organizations.Organization",
        on_delete=models.PROTECT,
        editable=False,
        related_name="statutory_profiles",
    )
    pf_mode = models.CharField(max_length=5, choices=MODE_CHOICES, default=MODE_AUTO)
    pf_on_full_wage = models.BooleanField(
        default=False,
        help_text="Contribute PF on the full wage instead of stopping at the ceiling."
    )
    esi_mode = models.CharField(max_length=5, choices=MODE_CHOICES, default=MODE_AUTO)
    tax_regime = models.CharField(max_length=3, choices=REGIME_CHOICES, default='NEW')
    tds_mode = models.CharField(
        max_length=5,
        choices=(('AUTO', 'Auto-calculate'), ('NA', 'Not applicable')),
        default='AUTO',
        help_text="Auto-calculate TDS on salary, or switch it off for this employee."
    )
    declared_deductions = EncryptedDecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Old regime only: total yearly deductions and exemptions declared (80C, HRA and so on)."
    )
    work_state = models.CharField(
        max_length=40,
        blank=True,
        help_text="State where the employee works. Used for professional tax later."
    )
    gender = models.CharField(
        max_length=1,
        choices=(('M', 'Male'), ('F', 'Female')),
        blank=True,
        help_text="Needed for professional tax in states whose slabs differ for men and women."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=['organization'])]

    def save(self, *args, **kwargs):
        self.organization_id = self.employee.organization_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Statutory profile: {self.employee}"


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

    organization = models.ForeignKey(
        "app_organizations.Organization",
        on_delete=models.PROTECT,
        related_name="work_schedules",
    )

    name = models.CharField(
        max_length=100,
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
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_work_schedule_name_per_org",
            )
        ]

    def save(self, *args, **kwargs):
        if self.is_default:
            WorkSchedule.objects.filter(
                organization=self.organization,
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
    organization = models.ForeignKey(
        "app_organizations.Organization",
        on_delete=models.PROTECT,
        related_name="shifts",
    )
    name = models.CharField(max_length=50)  # e.g. "General Shift", "Night Shift"
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
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_shift_name_per_org",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.start_time.strftime('%H:%M')}–{self.end_time.strftime('%H:%M')})"

    def save(self, *args, **kwargs):
        # Enforce "only one default shift" — same pattern as Salary.is_active
        if self.is_default:
            ShiftMaster.objects.filter(
                organization=self.organization,
                is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


class DesignationMaster(models.Model):
    """Job designation lookup, e.g. 'Software Engineer', 'HR Manager'."""
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    organization = models.ForeignKey(
        "app_organizations.Organization",
        on_delete=models.PROTECT,
        related_name="designations",
    )
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Designation"
        verbose_name_plural = "Designations"
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_designation_name_per_org",
            )
        ]

    def __str__(self):
        return self.name


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

    organization = models.ForeignKey(
        "app_organizations.Organization",
        on_delete=models.PROTECT,
        related_name="leave_types",
    )

    name = models.CharField(
        max_length=100,
        help_text="Example: Casual Leave, Sick Leave, Earned Leave."
    )

    code = models.CharField(
        max_length=20,
        help_text="Short code such as CL, SL, EL or LOP, unique within the organization."
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
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_leave_type_name_per_org",
            ),
            models.UniqueConstraint(
                fields=["organization", "code"],
                name="unique_leave_type_code_per_org",
            ),
        ]

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

    organization = models.ForeignKey(
        "app_organizations.Organization",
        on_delete=models.PROTECT,
        related_name="holidays",
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
                fields=["organization", "name", "date"],
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



def emp_document_path(instance, filename):
    return f"employee_documents/{instance.employee.uuid}/{filename}"


 
MAX_DOCUMENT_SIZE_KB = 200
ALLOWED_DOCUMENT_EXTENSIONS = ["pdf", "jpg", "jpeg", "png", "docx"]
MAX_IMAGE_DIMENSION = 1600  # px, longest side
 
 
def compress_image_if_needed(file, max_kb=MAX_DOCUMENT_SIZE_KB, max_dimension=MAX_IMAGE_DIMENSION):
    """
    Server-side safety net: if an uploaded JPG/PNG is over max_kb, re-encode
    it at progressively lower quality until it fits (or we hit the floor).
    Runs even if client-side JS compression was skipped/bypassed.
    Returns the (possibly replaced) file unchanged for non-images or files
    already under the limit.
    """
    name = getattr(file, "name", "") or ""
    if not name.lower().endswith((".jpg", ".jpeg", ".png")):
        return file  # PDFs / docx: nothing we can safely do here
 
    if file.size <= max_kb * 1024:
        return file  # already small enough
 
    try:
        file.seek(0)
        img = Image.open(file)
        img = img.convert("RGB")  # drop alpha/PNG palette so JPEG re-encode works
    except UnidentifiedImageError:
        return file  # not actually a valid image; let the extension/size validators reject it
 
    # Downscale if oversized
    img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
 
    for quality in (80, 60, 40, 25, 15):
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality, optimize=True)
        if buffer.tell() <= max_kb * 1024:
            break
 
    buffer.seek(0)
    new_name = name.rsplit(".", 1)[0] + ".jpg"
    return InMemoryUploadedFile(
        buffer,
        field_name=getattr(file, "field_name", None),
        name=new_name,
        content_type="image/jpeg",
        size=buffer.getbuffer().nbytes,
        charset=None,
    )
 
 
def validate_document_size(file):
    max_size_bytes = MAX_DOCUMENT_SIZE_KB * 1024
    if file.size > max_size_bytes:
        is_image = file.name.lower().endswith((".jpg", ".jpeg", ".png"))
        hint = (
            " Please retake the photo in better light or crop closer to the document."
            if is_image
            else " Please re-save/export the file at a smaller size (e.g. reduce PDF resolution)."
        )
        raise ValidationError(
            f"File too large ({file.size / 1024:.0f}KB). "
            f"Maximum allowed size is {MAX_DOCUMENT_SIZE_KB}KB.{hint}"
        )




class DocumentTypeMaster(models.Model):
    organization = models.ForeignKey(
        "app_organizations.Organization",
        on_delete=models.PROTECT,
        related_name="document_types",
    )
    name = models.CharField(
        max_length=50,
        help_text="e.g. Aadhar Card, Resume, Offer Letter"
    )

    description = models.CharField(
        max_length=255,
        null=True,
        blank=True
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Inactive types won't show up as options for new uploads."
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Document Type"
        verbose_name_plural = "Document Types"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_document_type_name_per_org",
            )
        ]

    def __str__(self):
        return self.name


class empDocument(models.Model):
    employee = models.ForeignKey(
        "empProfile",
        on_delete=models.CASCADE,
        related_name="documents"
    )

    document_type = models.ForeignKey(
        DocumentTypeMaster,
        on_delete=models.PROTECT,
        related_name="documents"
    )

    file = models.FileField(
        upload_to=emp_document_path,
        validators=[
            FileExtensionValidator(allowed_extensions=ALLOWED_DOCUMENT_EXTENSIONS),
            validate_document_size,
        ]
    )

    uploaded_at = models.DateTimeField(auto_now_add=True)

    is_verified = models.BooleanField(
        default=False,
        help_text="Whether HR has verified this document."
    )

    # ── New: rejection support ──────────────────────────
    is_rejected = models.BooleanField(
        default=False,
        help_text="Whether HR has rejected this document."
    )

    rejection_reason = models.TextField(
        null=True,
        blank=True,
        help_text="Why HR rejected this document (shown to the employee)."
    )

    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents_reviewed",
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = "Employee Document"
        verbose_name_plural = "Employee Documents"

    def __str__(self):
        return f"{self.employee} - {self.document_type.name}"
        
class EmployeeImportFieldConfig(models.Model):
    TARGET_CHOICES = [
        ("USER", "User Account"),
        ("PROFILE", "Employee Profile"),
    ]

    DATA_TYPE_CHOICES = [
        ("TEXT", "Text"),
        ("FULL_NAME", "Full Name (splits into first/last)"),
        ("EMAIL", "Email"),
        ("DATE", "Date"),
        ("PHONE", "Phone Number"),
        ("REGEX", "Text (custom pattern)"),
        ("DESIGNATION_FK", "Designation (lookup / create)"),
    ]

    organization = models.ForeignKey(
        "app_organizations.Organization",
        on_delete=models.PROTECT,
        related_name="import_field_configs",
    )
    field_key = models.CharField(
        max_length=50,
        help_text="Internal field name, e.g. 'aadhar_no', 'email', 'full_name'.",
    )
    column_label = models.CharField(
        max_length=100,
        help_text="Exact header text expected in the uploaded sheet, e.g. 'Aadhar No.'",
    )
    display_name = models.CharField(
        max_length=100,
        help_text="Label shown in the import preview table.",
    )
    target_model = models.CharField(max_length=10, choices=TARGET_CHOICES)
    data_type = models.CharField(max_length=20, choices=DATA_TYPE_CHOICES)
    is_required = models.BooleanField(default=False)
    validation_regex = models.CharField(
        max_length=200, blank=True,
        help_text="Only used when data_type = 'Text (custom pattern)'.",
    )
    validation_message = models.CharField(
        max_length=200, blank=True,
        help_text="Error shown when validation_regex doesn't match.",
    )
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "field_key"]
        verbose_name = "Employee Import Field"
        verbose_name_plural = "Employee Import Fields"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "field_key"],
                name="unique_import_field_key_per_org",
            )
        ]

    def __str__(self):
        return f"{self.column_label} → {self.field_key}"
    
class Airport(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=10, unique=True)
    state = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["state", "name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


PASS_TYPE_CHOICES = (
    ("AVSEC", "AVSEC"), ("AOCC", "AOCC"), ("RAP", "RAP"),
    ("VEP", "VEP"), ("VISITOR", "Visitor"), ("CONTRACTOR", "Contractor"),
)
MANUAL_STATUS_CHOICES = (("SUSPENDED", "Suspended"), ("SURRENDERED", "Surrendered"))


class BCASPass(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    employee = models.ForeignKey(empProfile, on_delete=models.CASCADE, related_name="bcas_passes")
    organization = models.ForeignKey(
        "app_organizations.Organization",
        on_delete=models.PROTECT,
        editable=False,
        related_name="bcas_passes",
    )
    pass_type = models.CharField(max_length=15, choices=PASS_TYPE_CHOICES)
    airport = models.ForeignKey(Airport, on_delete=models.PROTECT, related_name="bcas_passes")
    issue_date = models.DateField()
    expiry_date = models.DateField()
    access_zones = models.CharField(max_length=255, blank=True)
    issuing_authority = models.CharField(max_length=150, blank=True)
    remarks = models.TextField(blank=True)
    manual_status = models.CharField(max_length=15, choices=MANUAL_STATUS_CHOICES, null=True, blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        self.organization_id = self.employee.organization_id
        super().save(*args, **kwargs)

    @property
    def status(self):
        if self.manual_status:
            return self.manual_status
        today = timezone.localdate()
        if self.expiry_date < today:
            return "EXPIRED"
        if self.issue_date > today:
            return "PENDING"
        return "ACTIVE"

    @property
    def is_expiring_soon(self):
        return self.status == "ACTIVE" and (self.expiry_date - timezone.localdate()).days <= 30

    @property
    def police_verification_pending(self):
        return self.employee.police_verification_date is None

    def __str__(self):
        return f"{self.employee} — {self.get_pass_type_display()} ({self.airport.code})"
    
class WhatsAppTicket(models.Model):

    CATEGORY_CHOICES = [
        ("leave", "Leave"),
        ("attendance", "Attendance"),
        ("payroll", "Payroll"),
        ("general", "General"),
    ]

    STATUS_CHOICES = [
        ('new', 'New'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
        ('auto_resolved', 'Auto-resolved'),
    ]

    wa_message_id = models.CharField(max_length=100, unique=True)
    sender_wa_id = models.CharField(max_length=20)       # employee's WhatsApp number
    sender_name = models.CharField(max_length=100, blank=True)
    message_body = models.TextField()
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="general")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Ticket #{self.id} from {self.sender_name or self.sender_wa_id}"