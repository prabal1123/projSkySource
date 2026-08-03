from django.contrib import admin
from .models import empProfile, Attendance

admin.site.register(empProfile)

@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('employee', 'date', 'status', 'check_in', 'check_out', 'marked_by')
    list_filter = ('status', 'date')
    search_fields = ('employee__user__first_name', 'employee__user__last_name')