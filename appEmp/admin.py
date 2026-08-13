from django.contrib import admin
from .models import empProfile, Attendance , ShiftMaster, DesignationMaster,AttendanceException,LeaveTypeMaster,LeaveBalance,LeaveRequest
from .models import Holiday,WorkSchedule

# admin.site.register(empProfile)
@admin.register(empProfile)
class EmployeeAdmin(admin.ModelAdmin):
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
        "phone_number",
    )



@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('employee', 'date', 'status', 'check_in', 'check_out', 'marked_by')
    list_filter = ('status', 'date')
    search_fields = ('employee__user__first_name', 'employee__user__last_name')


@admin.register(ShiftMaster)
class ShiftMasterAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_time', 'end_time', 'is_night_shift', 'grace_period_minutes', 'is_default', 'is_active')
    list_filter = ('is_default', 'is_active', 'is_night_shift')
    search_fields = ('name',)


@admin.register(DesignationMaster)
class DesignationMasterAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name',)


# @admin.register(RoleMaster)
# class RoleMasterAdmin(admin.ModelAdmin):
#     list_display = ('name', 'is_active', 'created_at')
#     list_filter = ('is_active',)
#     search_fields = ('name',)

@admin.register(AttendanceException)
class AttendanceExceptionAdmin(admin.ModelAdmin):
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
class LeaveTypeMasterAdmin(admin.ModelAdmin):
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
class LeaveBalanceAdmin(admin.ModelAdmin):
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
class LeaveRequestAdmin(admin.ModelAdmin):
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
class HolidayAdmin(admin.ModelAdmin):
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
class WorkScheduleAdmin(admin.ModelAdmin):
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
    