from django import forms
from django.contrib import admin

from .entitlements import direct_module_keys
from .models import Organization, OrganizationMember, OrganizationModule
from .modules import MODULES, effective_modules


class OrganizationModuleForm(forms.ModelForm):
    module_key = forms.ChoiceField(
        choices=[(k, m["label"]) for k, m in MODULES.items()]
    )

    class Meta:
        model = OrganizationModule
        fields = "__all__"


class OrganizationModuleInline(admin.TabularInline):
    model = OrganizationModule
    form = OrganizationModuleForm
    extra = 0


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "created_by", "created_at")
    search_fields = ("name",)
    inlines = [OrganizationModuleInline]
    readonly_fields = ("modules_summary",)

    @admin.display(description="Active modules (right now)")
    def modules_summary(self, obj):
        if obj is None or obj.pk is None:
            return "-"
        direct = direct_module_keys(obj)
        active = effective_modules(direct)
        if not active:
            return "None (core only)"
        parts = []
        for key in MODULES:
            if key in active:
                label = MODULES[key]["label"]
                parts.append(label if key in direct else f"{label} (included)")
        return ", ".join(parts)


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
    