from django.contrib import admin

from .models import Organization, OrganizationMember


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "created_by", "created_at")
    search_fields = ("name",)


@admin.register(OrganizationMember)
class OrganizationMemberAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "role", "joined_at")
    list_filter = ("organization", "role")
    search_fields = ("user__username", "user__email")
    list_select_related = ("user", "organization")

    def get_readonly_fields(self, request, obj=None):
        # Changing org here would leave the employee profile in the old org.
        if obj is not None:
            return ("organization", "user")
        return ()

    def has_add_permission(self, request):
        # Every new user gets a membership automatically (appEmp signal).
        return False
