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
)
from django.db.models import Q


class EmployeeForm(forms.ModelForm):
    """
    Employee apni basic personal details update kar sakta hai.
    Manager, designation aur shift employee khud change nahi karega.
    """

    class Meta:
        model = empProfile
        fields = [
            "phone_number",
            "address",
            "state",
            "zip_code",
        ]

        widgets = {
            "phone_number": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "address": forms.Textarea(
                attrs={"rows": 3, "class": "form-control"}
            ),
            "state": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "zip_code": forms.TextInput(
                attrs={"class": "form-control"}
            ),
        }


class ProfileFormAdmin(forms.ModelForm):
    """
    HR/Admin/Manager employee profile update form.
    """

    class Meta:
        model = empProfile
        fields = [
            "role",
            "manager",
            "designation",
            "shift",
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

        # Only active shifts and designations should be selectable.
        self.fields["designation"].queryset = (
            DesignationMaster.objects
            .filter(is_active=True)
            .order_by("name")
        )

        self.fields["shift"].queryset = (
            ShiftMaster.objects
            .filter(is_active=True)
            .order_by("name")
        )

        # Only active employees can be selected as manager.
        manager_queryset = (
            empProfile.objects
            .filter(is_active=True)
            .select_related("user")
            .order_by("user__first_name", "user__last_name")
        )

        # Employee cannot select themselves as manager.
        if current_employee and current_employee.pk:
            manager_queryset = manager_queryset.exclude(
                pk=current_employee.pk
            )

        self.fields["manager"].queryset = manager_queryset

        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            else:
                field.widget.attrs.setdefault(
                    "class",
                    "form-control"
                )

    def clean_manager(self):
        manager = self.cleaned_data.get("manager")

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


# class LeaveRequestForm(forms.ModelForm):
#     class Meta:
#         model = LeaveRequest
#         fields = [
#             "leave_type",
#             "start_date",
#             "end_date",
#             "duration_type",
#             "reason",
#         ]

#         widgets = {
#             "leave_type": forms.Select(
#                 attrs={"class": "form-control"}
#             ),
#             "start_date": forms.DateInput(
#                 attrs={
#                     "type": "date",
#                     "class": "form-control",
#                 }
#             ),
#             "end_date": forms.DateInput(
#                 attrs={
#                     "type": "date",
#                     "class": "form-control",
#                 }
#             ),
#             "duration_type": forms.Select(
#                 attrs={"class": "form-control"}
#             ),
#             "reason": forms.Textarea(
#                 attrs={
#                     "class": "form-control",
#                     "rows": 5,
#                     "placeholder": "Enter the reason for your leave request.",
#                 }
#             ),
#         }

#     def __init__(self, *args, employee=None, **kwargs):
#         super().__init__(*args, **kwargs)

#         self.employee = employee

#         self.fields["leave_type"].queryset = (
#             LeaveTypeMaster.objects
#             .filter(is_active=True)
#             .order_by("name")
#         )

#         # Set employee before ModelForm runs model-level validation.
#         if self.employee:
#             self.instance.employee = self.employee

#     def clean(self):
#         cleaned_data = super().clean()

#         leave_type = cleaned_data.get("leave_type")
#         start_date = cleaned_data.get("start_date")
#         end_date = cleaned_data.get("end_date")
#         duration_type = cleaned_data.get("duration_type")

#         if not all([
#             self.employee,
#             leave_type,
#             start_date,
#             end_date,
#             duration_type,
#         ]):
#             return cleaned_data

#         today = timezone.localdate()

#         if start_date < today:
#             self.add_error(
#                 "start_date",
#                 "Past-date leave applications are not enabled yet."
#             )

#         if end_date < start_date:
#             self.add_error(
#                 "end_date",
#                 "End date cannot be before start date."
#             )
#             return cleaned_data

#         if start_date.year != end_date.year:
#             self.add_error(
#                 "end_date",
#                 "A leave request cannot currently span two calendar years."
#             )
#             return cleaned_data

#         if (
#             duration_type in ["FIRST_HALF", "SECOND_HALF"]
#             and start_date != end_date
#         ):
#             self.add_error(
#                 "duration_type",
#                 "Half-day leave can only be applied for one date."
#             )

#         if (
#             duration_type in ["FIRST_HALF", "SECOND_HALF"]
#             and not leave_type.allow_half_day
#         ):
#             self.add_error(
#                 "duration_type",
#                 f"{leave_type.name} does not allow half-day leave."
#             )

#         if duration_type in ["FIRST_HALF", "SECOND_HALF"]:
#             requested_days = Decimal("0.5")
#         else:
#             requested_days = Decimal(
#                 str((end_date - start_date).days + 1)
#             )

#         overlapping_request = LeaveRequest.objects.filter(
#             employee=self.employee,
#             status__in=["PENDING", "APPROVED"],
#             start_date__lte=end_date,
#             end_date__gte=start_date,
#         )

#         if self.instance.pk:
#             overlapping_request = overlapping_request.exclude(
#                 pk=self.instance.pk
#             )

#         if overlapping_request.exists():
#             raise forms.ValidationError(
#                 "A pending or approved leave request already exists for these dates."
#             )

#         present_attendance_exists = Attendance.objects.filter(
#             employee=self.employee,
#             date__range=(start_date, end_date),
#             status="PRESENT",
#         ).exists()

#         if present_attendance_exists:
#             raise forms.ValidationError(
#                 "Leave cannot be applied because attendance is already marked Present for one or more selected dates."
#             )

#         leave_balance = LeaveBalance.objects.filter(
#             employee=self.employee,
#             leave_type=leave_type,
#             year=start_date.year,
#         ).first()

#         if not leave_balance:
#             self.add_error(
#                 "leave_type",
#                 f"No {start_date.year} leave balance has been assigned for this leave type."
#             )
#             return cleaned_data

#         if leave_balance.available_balance < requested_days:
#             self.add_error(
#                 "leave_type",
#                 (
#                     f"Insufficient balance. Available: "
#                     f"{leave_balance.available_balance}, "
#                     f"Requested: {requested_days}."
#                 )
#             )

#         return cleaned_data


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
    class Meta:
        model = LeaveBalance
        fields = [
            "employee",
            "leave_type",
            "year",
            "total_allotted",
            "adjustment",
            "remarks",
        ]

        widgets = {
            "employee": forms.Select(attrs={"class": "form-control"}),
            "leave_type": forms.Select(attrs={"class": "form-control"}),
            "year": forms.NumberInput(attrs={
                "class": "form-control",
                "min": "2020",
            }),
            "total_allotted": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.5",
                "min": "0",
            }),
            "adjustment": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.5",
            }),
            "remarks": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["employee"].queryset = (
            empProfile.objects
            .filter(is_active=True)
            .select_related("user")
            .order_by("user__first_name", "user__last_name")
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

        if employee and leave_type and year:
            existing = LeaveBalance.objects.filter(
                employee=employee,
                leave_type=leave_type,
                year=year,
            )

            if self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)

            if existing.exists():
                raise forms.ValidationError(
                    "A leave balance already exists for this employee, leave type and year."
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