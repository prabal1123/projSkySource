from datetime import time

SHIFTS = [
    {"name": "General Shift", "start_time": time(9, 0), "end_time": time(18, 0),
     "is_night_shift": False, "grace_period_minutes": 10, "make_default": True},
    {"name": "Night Shift", "start_time": time(22, 0), "end_time": time(6, 0),
     "is_night_shift": True, "grace_period_minutes": 10, "make_default": False},
]

LEAVE_TYPES = [
    {"name": "Casual Leave", "code": "CL", "is_paid": True,
     "allow_half_day": True, "requires_document": False},
    {"name": "Earned Leave", "code": "EL", "is_paid": True,
     "allow_half_day": True, "requires_document": False},
    {"name": "Loss of Pay", "code": "LOP", "is_paid": False,
     "allow_half_day": False, "requires_document": False},
    {"name": "Sick Leave", "code": "SL", "is_paid": True,
     "allow_half_day": True, "requires_document": True},
]

DOCUMENT_TYPES = [
    {"name": "Aadhar Card", "description": "Government-issued Aadhar identity card"},
    {"name": "Offer Letter", "description": "Signed offer letter"},
    {"name": "PAN Card", "description": "Permanent Account Number card"},
    {"name": "Resume", "description": "Employee resume / CV"},
]

WORK_SCHEDULES = [
    {"name": "Standard 5-Day Week",
     "monday": True, "tuesday": True, "wednesday": True,
     "thursday": True, "friday": True, "saturday": False, "sunday": False,
     "make_default": True},
]


def _seed(model, org, rows):
    """Create missing rows for this org, matched on name. Returns count created."""
    created = 0
    has_default = (
        hasattr(model, "is_default")
        and model.objects.filter(organization=org, is_default=True).exists()
    )
    for row in rows:
        row = dict(row)
        name = row.pop("name")
        make_default = row.pop("make_default", False)
        if make_default and not has_default:
            row["is_default"] = True
        elif "make_default" in rows[0] or make_default:
            row["is_default"] = False
        _, was_created = model.objects.get_or_create(
            organization=org, name=name, defaults=row
        )
        if was_created:
            created += 1
            if row.get("is_default"):
                has_default = True
    return created


def seed_org_defaults(org):
    """
    Give a new organization its starting masters.
    Safe to run twice: existing rows (same name in this org) are left alone.
    Returns a dict of how many rows were created per master.
    """
    from appEmp.models import (
        DocumentTypeMaster,
        LeaveTypeMaster,
        ShiftMaster,
        WorkSchedule,
    )

    return {
        "shifts": _seed(ShiftMaster, org, SHIFTS),
        "leave_types": _seed(LeaveTypeMaster, org, LEAVE_TYPES),
        "document_types": _seed(DocumentTypeMaster, org, DOCUMENT_TYPES),
        "work_schedules": _seed(WorkSchedule, org, WORK_SCHEDULES),
    }


IMPORT_CONFIG_FIELDS = (
    "column_label",
    "display_name",
    "target_model",
    "data_type",
    "is_required",
    "validation_regex",
    "validation_message",
    "order",
    "is_active",
)


def copy_import_config(org, source_org=None):
    """
    Copy the employee-import field config rows from source_org to org.
    source_org defaults to the first organization by id (yugaamAi).
    Safe to run twice: rows are matched on (organization, field_key).
    Returns the number of rows created.
    """
    from appEmp.models import EmployeeImportFieldConfig
    from .models import Organization

    if source_org is None:
        source_org = Organization.objects.order_by("id").first()
    if source_org is None or source_org.pk == org.pk:
        return 0

    created = 0
    for row in EmployeeImportFieldConfig.objects.filter(organization=source_org):
        defaults = {name: getattr(row, name) for name in IMPORT_CONFIG_FIELDS}
        _, was_created = EmployeeImportFieldConfig.objects.get_or_create(
            organization=org,
            field_key=row.field_key,
            defaults=defaults,
        )
        if was_created:
            created += 1
    return created


ORG_ADMIN_GROUP = "ORG_ADMIN"

ORG_ADMIN_PERMISSIONS = (
    "view_hr_dashboard",
    "manage_employees",
    "manage_attendance",
    "manage_leave_balance",
    "manage_salary",
    "review_leave",
    "review_attendance_exception",
    "review_finance_noc",
    "view_all_clearance_requests",
    "apply_clearance_for_employee",
    "initiate_employee_exit",
    "finalize_employee_exit",
)


def ensure_org_admin_group():
    """
    Return the ORG_ADMIN group, creating it if needed, holding exactly the
    12 custom appEmp permissions the app checks (no model add/change/delete/view
    permissions, nothing for Django's own tables).
    Raises RuntimeError, creating nothing, if any permission does not exist.
    """
    from django.contrib.auth.models import Group, Permission

    perms = Permission.objects.filter(
        content_type__app_label="appEmp",
        codename__in=ORG_ADMIN_PERMISSIONS,
    )
    found = set(perms.values_list("codename", flat=True))
    missing = set(ORG_ADMIN_PERMISSIONS) - found
    if missing:
        raise RuntimeError(
            "Missing appEmp permissions: " + ", ".join(sorted(missing))
        )

    group, _ = Group.objects.get_or_create(name=ORG_ADMIN_GROUP)
    group.permissions.set(perms)
    return group
