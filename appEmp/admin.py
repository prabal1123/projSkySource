from django.contrib import admin
from .models import empProfile, Attendance , ShiftMaster, DesignationMaster,AttendanceException,LeaveTypeMaster,LeaveBalance,LeaveRequest
from .models import Holiday,WorkSchedule
from .models import DocumentTypeMaster, empDocument,WhatsAppTicket
from .models import EmployeeImportFieldConfig
from .models import WhatsAppOTP, Airport, BCASPass
from .models import Salary, WageRegisterEntry
# admin.site.register(empProfile)
from django.core.exceptions import FieldDoesNotExist


class OrgColumnMixin:
    """
    Superuser-only admin: show and filter by the owning organization.
    org_path is a lookup such as "organization" or "employee__organization".
    If the path does not exist on the model, nothing is added.
    """

    org_path = "organization"

    def _org_path_valid(self):
        model = self.model
        for part in self.org_path.split("__"):
            try:
                field = model._meta.get_field(part)
            except FieldDoesNotExist:
                return False
            if not field.is_relation:
                return False
            model = field.related_model
        return True

    def get_list_display(self, request):
        cols = list(super().get_list_display(request))
        if self._org_path_valid() and "admin_org" not in cols:
            cols.append("admin_org")
        return cols

    def get_list_filter(self, request):
        flt = list(super().get_list_filter(request))
        if self._org_path_valid() and self.org_path not in flt:
            flt.insert(0, self.org_path)
        return flt

    def admin_org(self, obj):
        for part in self.org_path.split("__"):
            obj = getattr(obj, part, None)
            if obj is None:
                return "-"
        return obj

    admin_org.short_description = "Organization"


@admin.register(empProfile)

class EmployeeAdmin(OrgColumnMixin, admin.ModelAdmin):
    org_path = "organization"
    list_display = (
        "user",
        # "role",
        "designation",
        "shift",
        "manager",
        "is_active",
    )

    list_filter = (
        # "role",
        "is_active",
        "designation",
        "shift",
    )

    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "user__email",
    )

    SENSITIVE_FIELDS = (
        "aadhar_no",
        "pan_no",
        "bank_account_no",
        "uan_no",
        "esic_no",
        "phone_number",
        "address",
    )

    def get_exclude(self, request, obj=None):
        exclude = list(super().get_exclude(request, obj) or [])
        if not request.user.is_superuser:
            exclude += list(self.SENSITIVE_FIELDS)
        return exclude


@admin.register(WhatsAppOTP)
class WhatsAppOTPAdmin(admin.ModelAdmin):
    list_display = ("phone_number", "code", "used", "created_at")
    list_filter = ("used",)
    search_fields = ("phone_number",)
    readonly_fields = ("created_at",)

@admin.register(EmployeeImportFieldConfig)
class EmployeeImportFieldConfigAdmin(OrgColumnMixin, admin.ModelAdmin):
    org_path = "organization"
    list_display = (
        "order", "column_label", "field_key", "display_name",
        "target_model", "data_type", "is_required", "is_active",
    )
    list_display_links = ("field_key",)
    list_editable = ("column_label", "is_required", "is_active", "order")
    ordering = ("order",)


@admin.register(Attendance)
class AttendanceAdmin(OrgColumnMixin, admin.ModelAdmin):
    org_path = "employee__organization"
    list_display = ('employee', 'date', 'status', 'check_in', 'check_out', 'marked_by')
    list_filter = ('status', 'date')
    search_fields = ('employee__user__first_name', 'employee__user__last_name')


@admin.register(ShiftMaster)
class ShiftMasterAdmin(OrgColumnMixin, admin.ModelAdmin):
    org_path = "organization"
    list_display = ('name', 'start_time', 'end_time', 'is_night_shift', 'grace_period_minutes', 'is_default', 'is_active')
    list_filter = ('is_default', 'is_active', 'is_night_shift')
    search_fields = ('name',)


@admin.register(DesignationMaster)
class DesignationMasterAdmin(OrgColumnMixin, admin.ModelAdmin):
    org_path = "organization"
    list_display = ('name', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name',)


# @admin.register(RoleMaster)
# class RoleMasterAdmin(admin.ModelAdmin):
#     list_display = ('name', 'is_active', 'created_at')
#     list_filter = ('is_active',)
#     search_fields = ('name',)

@admin.register(AttendanceException)
class AttendanceExceptionAdmin(OrgColumnMixin, admin.ModelAdmin):
    org_path = "attendance__employee__organization"
    list_display = (
        "attendance",
        "raised_by",
        "status",
        "reviewed_by",
        "created_at",
    )

    list_filter = (
        "status",
        "created_at",
    )

    search_fields = (
        "attendance__employee__user__first_name",
        "attendance__employee__user__last_name",
        "attendance__employee__user__username",
        "reason",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

@admin.register(LeaveTypeMaster)
class LeaveTypeMasterAdmin(OrgColumnMixin, admin.ModelAdmin):
    org_path = "organization"
    list_display = (
        "name",
        "code",
        "is_paid",
        "allow_half_day",
        "requires_document",
        "is_active",
        "created_at",
    )

    list_filter = (
        "is_paid",
        "allow_half_day",
        "requires_document",
        "is_active",
    )

    search_fields = (
        "name",
        "code",
        "description",
    )

    readonly_fields = (
        "uuid",
        "created_at",
        "updated_at",
    )

    ordering = (
        "name",
    )

@admin.register(LeaveBalance)
class LeaveBalanceAdmin(OrgColumnMixin, admin.ModelAdmin):
    org_path = "employee__organization"
    list_display = (
        "employee",
        "leave_type",
        "year",
        "total_allotted",
        "used",
        "adjustment",
        "display_available_balance",
        "assigned_by",
        "updated_at",
    )

    list_filter = (
        "year",
        "leave_type",
    )

    search_fields = (
        "employee__user__first_name",
        "employee__user__last_name",
        "employee__user__username",
        "leave_type__name",
        "leave_type__code",
    )

    readonly_fields = (
        "uuid",
        "display_available_balance",
        "created_at",
        "updated_at",
    )

    autocomplete_fields = (
        "employee",
        "leave_type",
    )

    fieldsets = (
        (
            "Assignment",
            {
                "fields": (
                    "employee",
                    "leave_type",
                    "year",
                )
            },
        ),
        (
            "Balance",
            {
                "fields": (
                    "total_allotted",
                    "used",
                    "adjustment",
                    "display_available_balance",
                )
            },
        ),
        (
            "Administration",
            {
                "fields": (
                    "assigned_by",
                    "remarks",
                    "uuid",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    @admin.display(description="Available")
    def display_available_balance(self, obj):
        if not obj:
            return "—"

        return obj.available_balance

    def save_model(self, request, obj, form, change):
        if not obj.assigned_by:
            obj.assigned_by = request.user

        super().save_model(request, obj, form, change)


@admin.register(LeaveRequest)
class LeaveRequestAdmin(OrgColumnMixin, admin.ModelAdmin):
    org_path = "employee__organization"
    list_display = (
        "employee",
        "leave_type",
        "start_date",
        "end_date",
        "number_of_days",
        "duration_type",
        "status",
        "reviewed_by",
        "created_at",
    )

    list_filter = (
        "status",
        "leave_type",
        "duration_type",
        "start_date",
        "end_date",
    )

    search_fields = (
        "employee__user__username",
        "employee__user__first_name",
        "employee__user__last_name",
        "leave_type__name",
        "leave_type__code",
        "reason",
        "manager_comment",
    )

    readonly_fields = (
        "uuid",
        "number_of_days",
        "created_at",
        "updated_at",
    )

    autocomplete_fields = (
        "employee",
        "leave_type",
        "reviewed_by",
    )

    fieldsets = (
        (
            "Leave Details",
            {
                "fields": (
                    "employee",
                    "leave_type",
                    "start_date",
                    "end_date",
                    "duration_type",
                    "number_of_days",
                    "reason",
                )
            },
        ),
        (
            "Review",
            {
                "fields": (
                    "status",
                    "reviewed_by",
                    "reviewed_at",
                    "manager_comment",
                )
            },
        ),
        (
            "System Information",
            {
                "fields": (
                    "uuid",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

@admin.register(Holiday)
class HolidayAdmin(OrgColumnMixin, admin.ModelAdmin):
    org_path = "organization"
    list_display = (
        "name",
        "date",
        "holiday_type",
        "is_active",
        "created_by",
    )

    list_filter = (
        "holiday_type",
        "is_active",
        "date",
    )

    search_fields = (
        "name",
        "description",
    )

    ordering = ("date",)

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user

        super().save_model(request, obj, form, change)

@admin.register(WorkSchedule)
class WorkScheduleAdmin(OrgColumnMixin, admin.ModelAdmin):
    org_path = "organization"
    list_display = (
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
    )

    list_filter = (
        "is_default",
        "is_active",
    )

    search_fields = (
        "name",
    )

    list_editable = (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "is_default",
        "is_active",
    )


@admin.register(DocumentTypeMaster)
class DocumentTypeMasterAdmin(OrgColumnMixin, admin.ModelAdmin):
    org_path = "organization"
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(empDocument)
class empDocumentAdmin(OrgColumnMixin, admin.ModelAdmin):
    org_path = "employee__organization"
    list_display = ("employee", "document_type", "uploaded_at", "is_verified")
    list_filter = ("document_type", "is_verified")
    search_fields = ("employee__user__first_name", "employee__user__last_name")
    

@admin.register(Airport)
class AirportAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "state", "is_active")
    list_filter = ("state", "is_active")
    search_fields = ("name", "code", "state")
    list_editable = ("is_active",)
    ordering = ("state", "name")


@admin.register(BCASPass)
class BCASPassAdmin(OrgColumnMixin, admin.ModelAdmin):
    org_path = "organization"
    list_display = (
        "employee", "pass_type", "airport", "issue_date",
        "expiry_date", "status", "manual_status", "created_by",
    )
    list_filter = ("pass_type", "manual_status", "airport__state", "airport")
    search_fields = (
        "employee__user__first_name",
        "employee__user__last_name",
        "issuing_authority",
    )
    autocomplete_fields = ("employee", "airport")
    readonly_fields = ("uuid", "created_at", "updated_at")

    @admin.display(description="Status")
    def status(self, obj):
        return obj.status
    

@admin.register(WhatsAppTicket)
class WhatsAppTicketAdmin(admin.ModelAdmin):
    list_display = ('id', 'sender_name', 'sender_wa_id', 'category', 'status', 'created_at')
    list_filter = ('category', 'status')
    search_fields = ('sender_name', 'sender_wa_id', 'message_body')

@admin.register(Salary)
class SalaryAdmin(OrgColumnMixin, admin.ModelAdmin):
    org_path = "organization"
    list_display = ('employee', 'wage_type', 'basic_salary', 'hra', 'daily_rate', 'effective_date', 'is_active')
    list_filter = ('wage_type', 'is_active')
    search_fields = ('employee__user__first_name', 'employee__user__last_name')


@admin.register(WageRegisterEntry)
class WageRegisterEntryAdmin(OrgColumnMixin, admin.ModelAdmin):
    org_path = "organization"
    list_display = (
        'salary', 'wage_month', 'days_worked', 'operational_ot_hours',
        'national_holidays_in_month', 'gross_total', 'net_payment', 'payment_date',
    )
    list_filter = ('wage_month',)
    search_fields = ('salary__employee__user__first_name', 'salary__employee__user__last_name')

    readonly_fields = (
        'days_worked', 'operational_ot_hours', 'ot_hours_per_day', 'rate_of_wages',
        'total_operational_ot', 'national_holiday_wage', 'total_days',
        'total_wages_workday', 'total_wages_workday_nh', 'bonus', 'gross_total',
        'epf_employee', 'epf_employer', 'esic', 'total_deduction', 'net_payment',
    )

    fieldsets = (
        (None, {
            'fields': ('salary', 'wage_month')
        }),
        ('Inputs (editable)', {
            'fields': (
                'rate_override', 'national_holidays_in_month',
                'days_worked_override', 'ot_hours_override',
            )
        }),
        ('Computed — Days & OT', {
            'fields': ('days_worked', 'operational_ot_hours', 'ot_hours_per_day', 'rate_of_wages')
        }),
        ('Computed — Wages', {
            'fields': (
                'total_operational_ot', 'national_holiday_wage', 'total_days',
                'total_wages_workday', 'total_wages_workday_nh', 'bonus', 'gross_total',
            )
        }),
        ('Computed — Deductions & Net', {
            'fields': ('epf_employee', 'epf_employer', 'esic', 'total_deduction', 'net_payment')
        }),
        ('Payment (set after processing)', {
            'fields': ('mode_of_payment', 'payment_date')
        }),
    )
