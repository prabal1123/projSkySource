from django.contrib import admin

from appEmp.admin import OrgColumnMixin

from .models import Project


@admin.register(Project)
class ProjectAdmin(OrgColumnMixin, admin.ModelAdmin):
    list_display = ("name", "code", "status", "lead", "start_date", "end_date")
    list_filter = ("status",)
    search_fields = ("name", "code")
    raw_id_fields = ("lead",)
