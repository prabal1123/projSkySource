# from django import forms
# from .models import empProfile
# from .models import Attendance, Salary

# class EmployeeForm(forms.ModelForm):
#     class Meta:
#         model = empProfile
#         fields = [
#             "phone_number",
#             "address",
#             "state",
#             "zip_code",
#         ]

#         widgets = {
#             "address": forms.Textarea(
#                 attrs={"rows": 3}
#             ),
#         }


# class ProfileFormAdmin(forms.ModelForm):
#     class Meta:
#         model = empProfile
#         exclude = ["user"]

#         widgets = {
#             "date_hired": forms.DateInput(
#                 attrs={"type": "date", "class": "form-control"}
#             ),
#             "address": forms.Textarea(
#                 attrs={"rows": 3, "class": "form-control"}
#             ),
#         }

#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)

#         for name, field in self.fields.items():
#             if isinstance(field.widget, forms.CheckboxInput):
#                 field.widget.attrs["class"] = "form-check-input"
#             else:
#                 field.widget.attrs.setdefault("class", "form-control")


# class AttendanceUpdateForm(forms.ModelForm):
#     class Meta:
#         model = Attendance
#         fields = ['status', 'check_in', 'check_out']
#         widgets = {
#             'check_in': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
#             'check_out': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
#         }

# # ── Add to appEmp/forms.py ──────────────────────────────────────────────

# class SalaryForm(forms.ModelForm):
#     class Meta:
#         model = Salary
#         fields = ['basic_salary', 'hra', 'pf', 'effective_date']
#         widgets = {
#             'effective_date': forms.DateInput(attrs={'type': 'date'}),
#             'basic_salary': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
#             'hra': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
#             'pf': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
#         }

#     def clean_basic_salary(self):
#         val = self.cleaned_data['basic_salary']
#         if val <= 0:
#             raise forms.ValidationError("Basic salary must be greater than zero.")
#         return val


from django import forms
from django.utils import timezone
import datetime
from decimal import Decimal
from .models import (
    empProfile,
    Attendance,
    Salary,
    DesignationMaster,
    ShiftMaster,
    AttendanceException,
    LeaveRequest,
    LeaveTypeMaster,
    LeaveBalance,
    Holiday,
    WorkSchedule,
    OptionalHolidayRequest,
    Holiday,
)
from django import forms

from django.contrib.auth.models import Group
from django.db.models import Q




class EmployeeForm(forms.ModelForm):
    """
    Employee can update their own personal/contact details.

    Employment-related fields such as manager, designation,
    shift, joining date and verification status are controlled
    by HR and are not editable from My Profile.
    """

    username = forms.CharField(
        required=False,
        label="Username",
        disabled=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
            }
        ),
    )

    first_name = forms.CharField(
        required=False,
        label="First Name",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
            }
        ),
    )

    last_name = forms.CharField(
        required=False,
        label="Last Name",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
            }
        ),
    )

    email = forms.EmailField(
        required=False,
        label="Email Address",
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
            }
        ),
    )

    class Meta:
        model = empProfile

        fields = [
            # "username",
            "first_name",
            "last_name",
            "email",
            "phone_number",
            "state",
            "zip_code",
            "address",
        ]

        widgets = {
            "phone_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                }
            ),

            "state": forms.TextInput(
                attrs={
                    "class": "form-control",
                }
            ),

            "zip_code": forms.TextInput(
                attrs={
                    "class": "form-control",
                }
            ),

            "address": forms.Textarea(
                attrs={
                    "rows": 3,
                    "class": "form-control",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # User-related fields are stored on Django's User model,
        # not directly on empProfile.
        if (
            self.instance
            and self.instance.pk
            and self.instance.user_id
        ):
            user = self.instance.user

            self.fields["username"].initial = (
                user.username
            )

            self.fields["first_name"].initial = (
                user.first_name
            )

            self.fields["last_name"].initial = (
                user.last_name
            )

            self.fields["email"].initial = (
                user.email
            )

    def clean_email(self):
        email = (
            self.cleaned_data.get("email") or ""
        ).strip()

        if not email:
            return email

        # Prevent another user from already using the email.
        user_model = self.instance.user.__class__

        existing = (
            user_model.objects
            .filter(email__iexact=email)
            .exclude(pk=self.instance.user_id)
        )

        if existing.exists():
            raise forms.ValidationError(
                "Another account is already using this email address."
            )

        return email

    def save(self, commit=True):
        profile = super().save(
            commit=False
        )

        user = profile.user

        user.first_name = (
            self.cleaned_data.get("first_name") or ""
        ).strip()

        user.last_name = (
            self.cleaned_data.get("last_name") or ""
        ).strip()

        user.email = (
            self.cleaned_data.get("email") or ""
        ).strip()

        if commit:
            user.save(
                update_fields=[
                    "first_name",
                    "last_name",
                    "email",
                ]
            )

            profile.save()

        return profile


class ProfileFormAdmin(forms.ModelForm):
    """
    HR/Admin/Manager employee profile update form.
    """

    first_name = forms.CharField(
        required=False,
        label="First Name",
    )

    last_name = forms.CharField(
        required=False,
        label="Last Name",
    )

    email = forms.EmailField(
        required=False,
        label="Email Address",
    )

    access_group = forms.ModelChoiceField(
        queryset=Group.objects.none(),
        required=True,
        label="Access Group",
        help_text=(
            "Controls the employee's access level in the HRMS."
        ),
    )

    class Meta:
        model = empProfile
        fields = [
            "first_name",
            "last_name",
            "email",
            "access_group",
            "manager",
            "designation",
            "shift",
            "work_schedule",
            "phone_number",
            "position",
            "date_hired",
            "address",
            "state",
            "zip_code",
            "is_address_verified",
            "is_email_verified",
            "is_phone_verified",
            "is_background_check_completed",
            "is_aadhar_verified",
            "is_active",
            "is_default_manager",
        ]

        widgets = {
            "date_hired": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "form-control",
                }
            ),

            "address": forms.Textarea(
                attrs={
                    "rows": 3,
                    "class": "form-control",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        current_employee = self.instance
        if (
            current_employee
            and current_employee.pk
            and current_employee.user_id
        ):
            

            self.fields["first_name"].initial = (
                current_employee.user.first_name
            )

            self.fields["last_name"].initial = (
                current_employee.user.last_name
            )

            self.fields["email"].initial = (
                current_employee.user.email
            )

        # -----------------------------------------------------
        # Groups
        # -----------------------------------------------------

        self.fields["access_group"].queryset = (
            Group.objects
            .all()
            .order_by("name")
        )

        # Pre-select employee's current role/group.
        if (
            current_employee
            and current_employee.pk
            and current_employee.user_id
        ):
            current_group = (
                current_employee.user.groups
                .order_by("name")
                .first()
            )

            if current_group:
                self.fields["access_group"].initial = (
                    current_group
                )

        # -----------------------------------------------------
        # Designations
        # -----------------------------------------------------

        self.fields["designation"].queryset = (
            DesignationMaster.objects
            .filter(is_active=True)
            .order_by("name")
        )

        # -----------------------------------------------------
        # Shifts
        # -----------------------------------------------------

        self.fields["shift"].queryset = (
            ShiftMaster.objects
            .filter(is_active=True)
            .order_by("name")
        )
        # -----------------------------------------------------
        # Work Schedules
        # -----------------------------------------------------

        self.fields["work_schedule"].queryset = (
            WorkSchedule.objects
            .filter(is_active=True)
            .order_by("name")
        )

        # -----------------------------------------------------
        # Managers
        # -----------------------------------------------------

        manager_queryset = (
            empProfile.objects
            .filter(is_active=True)
            .select_related("user")
            .order_by(
                "user__first_name",
                "user__last_name",
            )
        )

        if current_employee and current_employee.pk:
            manager_queryset = manager_queryset.exclude(
                pk=current_employee.pk
            )

        self.fields["manager"].queryset = (
            manager_queryset
        )

        # -----------------------------------------------------
        # Bootstrap classes
        # -----------------------------------------------------

        for name, field in self.fields.items():
            if isinstance(
                field.widget,
                forms.CheckboxInput
            ):
                field.widget.attrs["class"] = (
                    "form-check-input"
                )

            else:
                field.widget.attrs.setdefault(
                    "class",
                    "form-control"
                )

    def clean_manager(self):
        manager = self.cleaned_data.get(
            "manager"
        )

        if (
            manager
            and self.instance
            and self.instance.pk
            and manager.pk == self.instance.pk
        ):
            raise forms.ValidationError(
                "An employee cannot be their own manager."
            )

        return manager

    def save(self, commit=True):
        profile = super().save(
            commit=False
        )

        selected_group = self.cleaned_data.get(
            "access_group"
        )

        if commit:
            profile.save()
            self.save_m2m()

            user = profile.user

            user.first_name = self.cleaned_data.get(
                "first_name",
                ""
            )

            user.last_name = self.cleaned_data.get(
                "last_name",
                ""
            )

            user.email = self.cleaned_data.get(
                "email",
                ""
            )

            user.save(
                update_fields=[
                    "first_name",
                    "last_name",
                    "email",
                ]
            )

            if not user.is_superuser:
                user.groups.clear()

                if selected_group:
                    user.groups.add(
                        selected_group
                    )

        return profile    

class AttendanceUpdateForm(forms.ModelForm):
    class Meta:
        model = Attendance
        fields = [
            "status",
            "check_in",
            "check_out",
        ]

        widgets = {
            "status": forms.Select(
                attrs={"class": "form-control"}
            ),
            "check_in": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                    "class": "form-control",
                },
                format="%Y-%m-%dT%H:%M",
            ),
            "check_out": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                    "class": "form-control",
                },
                format="%Y-%m-%dT%H:%M",
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["check_in"].input_formats = [
            "%Y-%m-%dT%H:%M"
        ]
        self.fields["check_out"].input_formats = [
            "%Y-%m-%dT%H:%M"
        ]


class SalaryForm(forms.ModelForm):
    class Meta:
        model = Salary
        fields = [
            "basic_salary",
            "hra",
            "pf",
            "effective_date",
        ]

        widgets = {
            "effective_date": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "form-control",
                }
            ),
            "basic_salary": forms.NumberInput(
                attrs={
                    "step": "0.01",
                    "min": "0",
                    "class": "form-control",
                }
            ),
            "hra": forms.NumberInput(
                attrs={
                    "step": "0.01",
                    "min": "0",
                    "class": "form-control",
                }
            ),
            "pf": forms.NumberInput(
                attrs={
                    "step": "0.01",
                    "min": "0",
                    "class": "form-control",
                }
            ),
        }

    def clean_basic_salary(self):
        value = self.cleaned_data["basic_salary"]

        if value <= 0:
            raise forms.ValidationError(
                "Basic salary must be greater than zero."
            )

        return value

class AttendanceExceptionForm(forms.ModelForm):
    class Meta:
        model = AttendanceException
        fields = ["reason"]

        widgets = {
            "reason": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 5,
                    "placeholder": (
                        "Explain why this attendance should be corrected. "
                        "For example: forgot to check in, system issue, "
                        "or worked from another location."
                    ),
                }
            ),
        }

        labels = {
            "reason": "Reason for regularisation",
        }




class LeaveRequestForm(forms.ModelForm):
    class Meta:
        model = LeaveRequest
        fields = [
            "leave_type",
            "start_date",
            "end_date",
            "duration_type",
            "reason",
        ]

        widgets = {
            "leave_type": forms.Select(
                attrs={
                    "class": "form-control"
                }
            ),

            "start_date": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "form-control",
                }
            ),

            "end_date": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "form-control",
                }
            ),

            "duration_type": forms.Select(
                attrs={
                    "class": "form-control"
                }
            ),

            "reason": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 5,
                    "placeholder": (
                        "Enter the reason for your leave request."
                    ),
                }
            ),
        }

    def __init__(self, *args, employee=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.employee = employee

        self.fields["leave_type"].queryset = (
            LeaveTypeMaster.objects
            .filter(is_active=True)
            .order_by("name")
        )

        # Model validation ko employee available hona chahiye.
        if self.employee:
            self.instance.employee = self.employee

    def clean(self):
        cleaned_data = super().clean()

        leave_type = cleaned_data.get("leave_type")
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        duration_type = cleaned_data.get("duration_type")

        # Required fields missing hain to Django ke normal
        # field-level errors handle karenge.
        if not all([
            self.employee,
            leave_type,
            start_date,
            end_date,
            duration_type,
        ]):
            return cleaned_data

        today = timezone.localdate()

        # -----------------------------------------------------
        # 1. Past-date validation
        # -----------------------------------------------------
        if start_date < today:
            self.add_error(
                "start_date",
                "Past-date leave applications are not enabled yet."
            )

        # -----------------------------------------------------
        # 2. Date range validation
        # -----------------------------------------------------
        if end_date < start_date:
            self.add_error(
                "end_date",
                "End date cannot be before start date."
            )
            return cleaned_data

        # -----------------------------------------------------
        # 3. Cross-year leave not supported yet
        # -----------------------------------------------------
        if start_date.year != end_date.year:
            self.add_error(
                "end_date",
                (
                    "A leave request cannot currently span "
                    "two calendar years."
                )
            )
            return cleaned_data

        # -----------------------------------------------------
        # 4. Half-day validation
        # -----------------------------------------------------
        is_half_day = duration_type in [
            "FIRST_HALF",
            "SECOND_HALF",
        ]

        if is_half_day and start_date != end_date:
            self.add_error(
                "duration_type",
                "Half-day leave can only be applied for one date."
            )

        if is_half_day and not leave_type.allow_half_day:
            self.add_error(
                "duration_type",
                (
                    f"{leave_type.name} does not allow "
                    "half-day leave."
                )
            )

        # -----------------------------------------------------
        # 5. Calculate requested leave days
        # -----------------------------------------------------
        if is_half_day:
            requested_days = Decimal("0.5")
        else:
            requested_days = Decimal(
                str(
                    (end_date - start_date).days + 1
                )
            )

        # -----------------------------------------------------
        # 6. Existing overlapping leave request
        # -----------------------------------------------------
        overlapping_requests = (
            LeaveRequest.objects
            .filter(
                employee=self.employee,
                status__in=[
                    "PENDING",
                    "APPROVED",
                ],
                start_date__lte=end_date,
                end_date__gte=start_date,
            )
        )

        if self.instance.pk:
            overlapping_requests = (
                overlapping_requests.exclude(
                    pk=self.instance.pk
                )
            )

        if overlapping_requests.exists():
            overlap = (
                overlapping_requests
                .order_by("start_date")
                .first()
            )

            raise forms.ValidationError(
                (
                    "A pending or approved leave request "
                    "already exists for "
                    f"{overlap.start_date.strftime('%d %b %Y')} "
                    f"to "
                    f"{overlap.end_date.strftime('%d %b %Y')}."
                )
            )

        # -----------------------------------------------------
        # 7. Attendance conflict
        #
        # Do not allow leave over dates where employee has
        # already worked / checked in.
        # -----------------------------------------------------
        worked_attendance = (
            Attendance.objects
            .filter(
                employee=self.employee,
                date__range=(
                    start_date,
                    end_date,
                ),
            )
            .filter(
                Q(
                    status__in=[
                        "PRESENT",
                        "LATE",
                        "HALF_DAY",
                    ]
                )
                |
                Q(
                    check_in__isnull=False
                )
                |
                Q(
                    check_out__isnull=False
                )
            )
            .order_by("date")
        )

        if worked_attendance.exists():
            conflict_dates = ", ".join(
                record.date.strftime("%d %b %Y")
                for record in worked_attendance
            )

            raise forms.ValidationError(
                (
                    "Leave cannot be applied because "
                    "attendance is already recorded for: "
                    f"{conflict_dates}."
                )
            )

        # -----------------------------------------------------
        # 8. Leave balance
        # -----------------------------------------------------
        leave_balance = (
            LeaveBalance.objects
            .filter(
                employee=self.employee,
                leave_type=leave_type,
                year=start_date.year,
            )
            .first()
        )

        if not leave_balance:
            self.add_error(
                "leave_type",
                (
                    f"No {start_date.year} leave balance "
                    "has been assigned for this leave type."
                )
            )
            return cleaned_data

        # -----------------------------------------------------
        # 9. Sufficient balance
        # -----------------------------------------------------
        if (
            leave_balance.available_balance
            < requested_days
        ):
            self.add_error(
                "leave_type",
                (
                    "Insufficient leave balance. "
                    f"Available: "
                    f"{leave_balance.available_balance}, "
                    f"Requested: {requested_days}."
                )
            )

        return cleaned_data

class LeaveRequestReviewForm(forms.ModelForm):
    action = forms.ChoiceField(
        choices=(
            ("APPROVE", "Approve"),
            ("REJECT", "Reject"),
        ),
        widget=forms.RadioSelect,
    )

    class Meta:
        model = LeaveRequest
        fields = [
            "action",
            "manager_comment",
        ]

        widgets = {
            "manager_comment": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Add approval or rejection remarks.",
                }
            ),
        }

        labels = {
            "manager_comment": "Manager Comment",
        }

    def clean(self):
        cleaned_data = super().clean()

        action = cleaned_data.get("action")
        comment = cleaned_data.get("manager_comment")

        if action == "REJECT" and not comment:
            self.add_error(
                "manager_comment",
                "A comment is required when rejecting a leave request."
            )

        return cleaned_data


class LeaveBalanceForm(forms.ModelForm):

    LEAVE_START_CHOICES = (
        ("TODAY", "From Today"),
        ("AFTER_PROBATION", "After 3 Months"),
        ("SELECTED_DATE", "From Selected Date"),
    )

    leave_start_mode = forms.ChoiceField(
        label="Leave Facility Starts",
        choices=LEAVE_START_CHOICES,
        initial="AFTER_PROBATION",
        widget=forms.Select(
            attrs={
                "class": "form-control",
            }
        ),
        help_text=(
            "Default company policy is after "
            "3 months from the employee's joining date."
        ),
    )

    selected_leave_start_date = forms.DateField(
        label="Selected Start Date",
        required=False,
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "form-control",
            }
        ),
    )

    class Meta:
        model = LeaveBalance

        fields = [
            "employee",
            "leave_type",
            "year",
            "total_allotted",
            "remarks",
        ]

        widgets = {
            "employee": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "leave_type": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "year": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "2020",
                }
            ),

            "total_allotted": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.5",
                    "min": "0",
                }
            ),

            "remarks": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["employee"].queryset = (
            empProfile.objects
            .filter(is_active=True)
            .select_related("user")
            .order_by(
                "user__first_name",
                "user__last_name",
            )
        )

        self.fields["leave_type"].queryset = (
            LeaveTypeMaster.objects
            .filter(is_active=True)
            .order_by("name")
        )

    def clean(self):
        cleaned_data = super().clean()

        employee = cleaned_data.get("employee")
        leave_type = cleaned_data.get("leave_type")
        year = cleaned_data.get("year")

        leave_start_mode = cleaned_data.get(
            "leave_start_mode"
        )

        selected_date = cleaned_data.get(
            "selected_leave_start_date"
        )

        # -------------------------------------------------
        # Prevent duplicate yearly leave balance
        # -------------------------------------------------

        if employee and leave_type and year:

            existing = LeaveBalance.objects.filter(
                employee=employee,
                leave_type=leave_type,
                year=year,
            )

            if self.instance.pk:
                existing = existing.exclude(
                    pk=self.instance.pk
                )

            if existing.exists():
                raise forms.ValidationError(
                    (
                        "A leave balance already exists "
                        "for this employee, leave type "
                        "and year."
                    )
                )

        # -------------------------------------------------
        # Leave facility start validation
        # -------------------------------------------------

        if (
            leave_start_mode == "AFTER_PROBATION"
            and employee
            and not employee.date_hired
        ):
            self.add_error(
                "leave_start_mode",
                (
                    "This employee does not have a joining "
                    "date. Add the joining date before using "
                    "the 3-month probation policy."
                ),
            )

        if leave_start_mode == "SELECTED_DATE":

            if not selected_date:
                self.add_error(
                    "selected_leave_start_date",
                    "Please select the leave facility start date.",
                )

            elif selected_date < timezone.localdate():
                self.add_error(
                    "selected_leave_start_date",
                    (
                        "Selected start date cannot "
                        "be in the past."
                    ),
                )

        return cleaned_data
    
class AttendanceExceptionReviewForm(forms.Form):
    action = forms.ChoiceField(
        choices=(
            ("APPROVE", "Approve"),
            ("REJECT", "Reject"),
        ),
        widget=forms.RadioSelect,
    )

    manager_comment = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Add review comments...",
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()

        action = cleaned_data.get("action")
        manager_comment = cleaned_data.get("manager_comment")

        if action == "REJECT" and not manager_comment:
            self.add_error(
                "manager_comment",
                "Please provide a reason when rejecting the request."
            )

        return cleaned_data

class ResignationForm(forms.Form):
    proposed_last_working_date = forms.DateField(
        label="Proposed Last Working Date",
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "form-control",
            }
        ),
    )

    reason = forms.CharField(
        label="Reason for Resignation",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 5,
                "placeholder": (
                    "Enter your reason for resignation."
                ),
            }
        ),
    )

    def clean_proposed_last_working_date(self):
        proposed_date = self.cleaned_data[
            "proposed_last_working_date"
        ]

        if proposed_date < timezone.localdate():
            raise forms.ValidationError(
                "Proposed last working date cannot be in the past."
            )

        return proposed_date

class ResignationReviewForm(forms.Form):
    decision = forms.ChoiceField(
        choices=(
            ("APPROVED", "Accept Resignation"),
            ("REJECTED", "Reject Resignation"),
        ),
        widget=forms.Select(
            attrs={
                "class": "form-control",
            }
        ),
    )

    final_last_working_date = forms.DateField(
        label="Final Last Working Date",
        required=False,
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "form-control",
            }
        ),
    )

    remarks = forms.CharField(
        label="HR Remarks",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Add HR remarks.",
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()

        decision = cleaned_data.get("decision")
        remarks = (cleaned_data.get("remarks") or "").strip()

        if decision == "REJECTED" and not remarks:
            self.add_error(
                "remarks",
                "HR remarks are required when rejecting a resignation.",
            )

        final_date = cleaned_data.get(
            "final_last_working_date"
        )

        if (
            decision == "APPROVED"
            and final_date
            and final_date < timezone.localdate()
        ):
            self.add_error(
                "final_last_working_date",
                "Final last working date cannot be in the past.",
            )

        return cleaned_data

class ClearanceApprovalDecisionForm(forms.Form):
    decision = forms.ChoiceField(
        choices=(
            ("APPROVED", "Approve"),
            ("REJECTED", "Reject"),
        ),
        widget=forms.Select(
            attrs={
                "class": "form-control",
            }
        ),
    )

    remarks = forms.CharField(
        label="Remarks",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Add remarks for this clearance decision.",
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()

        decision = cleaned_data.get("decision")
        remarks = (cleaned_data.get("remarks") or "").strip()

        if decision == "REJECTED" and not remarks:
            self.add_error(
                "remarks",
                "Remarks are required when rejecting a clearance.",
            )

        return cleaned_data

class TerminationForm(forms.Form):
    employee = forms.ModelChoiceField(
        queryset=empProfile.objects.none(),
        label="Employee",
        widget=forms.Select(
            attrs={
                "class": "form-control",
            }
        ),
    )

    final_last_working_date = forms.DateField(
        label="Final Last Working Date",
        required=False,
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "form-control",
            }
        ),
    )

    reason = forms.CharField(
        label="Termination Reason",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 5,
                "placeholder": "Enter the reason for termination.",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["employee"].queryset = (
            empProfile.objects
            .filter(is_active=True)
            .select_related("user")
            .order_by(
                "user__first_name",
                "user__last_name",
            )
        )

    def clean_final_last_working_date(self):
        final_date = self.cleaned_data.get(
            "final_last_working_date"
        )

        if final_date and final_date < timezone.localdate():
            raise forms.ValidationError(
                "Final last working date cannot be in the past."
            )

        return final_date

class HolidayForm(forms.ModelForm):
    class Meta:
        model = Holiday
        fields = [
            "name",
            "date",
            "holiday_type",
            "description",
            "is_active",
        ]

        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "date": forms.DateInput(
                attrs={
                    "class": "form-control",
                    "type": "date",
                }
            ),
            "holiday_type": forms.Select(
                attrs={"class": "form-control"}
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                }
            ),
        }

class HolidayBulkUploadForm(forms.Form):
    file = forms.FileField(
        label="Holiday File",
        help_text="Upload .xlsx or .csv file."
    )

    def clean_file(self):
        uploaded_file = self.cleaned_data["file"]

        allowed_extensions = (
            ".xlsx",
            ".csv",
        )

        if not uploaded_file.name.lower().endswith(
            allowed_extensions
        ):
            raise forms.ValidationError(
                "Please upload an Excel (.xlsx) or CSV (.csv) file."
            )

        return uploaded_file

class WorkScheduleForm(forms.ModelForm):
    class Meta:
        model = WorkSchedule
        fields = [
            "name",
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
            "is_default",
            "is_active",
        ]


class OptionalHolidayRequestForm(forms.ModelForm):

    class Meta:
        model = OptionalHolidayRequest

        fields = [
            "holiday",
            "reason",
        ]

        widgets = {
            "holiday": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "reason": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Reason (optional)",
                }
            ),
        }

    def __init__(
        self,
        *args,
        employee=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        today = timezone.localdate()

        holidays = Holiday.objects.filter(
            holiday_type="OPTIONAL",
            is_active=True,
            date__gte=today,
        ).order_by("date")

        # Don't show holidays already requested
        # by this employee.
        if employee:
            requested_holiday_ids = (
                OptionalHolidayRequest.objects
                .filter(
                    employee=employee,
                )
                .values_list(
                    "holiday_id",
                    flat=True,
                )
            )

            holidays = holidays.exclude(
                id__in=requested_holiday_ids,
            )

        self.fields["holiday"].queryset = holidays

        self.fields["holiday"].empty_label = (
            "Select Optional Holiday"
        )
