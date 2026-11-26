from django.contrib import admin

from .models import BiometricDevice, BiometricIdentity, PunchLog, SyncRun


@admin.register(BiometricDevice)
class BiometricDeviceAdmin(admin.ModelAdmin):
    list_display = ("serial_number", "name", "project", "organization", "is_active")
    list_filter = ("organization", "is_active")
    search_fields = ("serial_number", "name")
    list_select_related = ("project", "organization")


@admin.register(BiometricIdentity)
class BiometricIdentityAdmin(admin.ModelAdmin):
    list_display = ("device_code", "employee", "organization")
    list_filter = ("organization", ("employee", admin.EmptyFieldListFilter))
    search_fields = ("device_code",)
    raw_id_fields = ("employee",)
    list_select_related = ("employee", "organization")


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PunchLog)
class PunchLogAdmin(ReadOnlyAdmin):
    list_display = ("employee_code", "punch_time", "device", "direction")
    list_filter = ("organization", "device")
    search_fields = ("employee_code",)
    date_hierarchy = "punch_time"
    list_select_related = ("device",)
    list_per_page = 100
    show_full_result_count = False


@admin.register(SyncRun)
class SyncRunAdmin(ReadOnlyAdmin):
    list_display = (
        "started_at",
        "mode",
        "from_date",
        "to_date",
        "status",
        "api_calls",
        "records_fetched",
        "records_new",
        "records_skipped",
    )
    list_filter = ("organization", "status", "mode")
