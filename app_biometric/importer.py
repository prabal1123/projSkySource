"""Smart Office employee importer.

Three stages: parse_csv -> build_plan (collects every error, writes nothing)
-> apply_plan (one transaction.atomic, all or nothing).

Nothing in here prints or returns employee names or logins in messages.
"""
import csv
import re
from dataclasses import dataclass, field
from datetime import date

from django.contrib.auth import get_user_model
from django.db import transaction

from app_organizations.entitlements import seats_left
from app_organizations.models import Organization
from app_organizations.services import create_organization
from app_projects.models import Project
from appEmp.models import DesignationMaster, empProfile

from .models import BiometricDevice, BiometricIdentity

REQUIRED_COLUMNS = (
    "EmployeeCode",
    "EmployeeName",
    "DeviceCode",
    "Location",
    "Designation",
    "DOJ",
    "Status",
)
FLAG_COLUMNS = ("Company", "Department", "Category")
NO_DESIGNATION = {"", "none", "null", "-"}
PROJECT_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
USERNAME_DOMAIN = "smartoffice.invalid"
CODE_MAX = 64
POSITION_MAX = 50
NAME_PART_MAX = 150


class ImporterError(Exception):
    """A problem with a safe, name-free message."""


@dataclass
class Row:
    line: int
    code: str
    name: str
    location: str
    designation: str
    doj: object = None
    flags: list = field(default_factory=list)


@dataclass
class ParseResult:
    rows: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    total_rows: int = 0
    skipped_status: int = 0
    skipped_codes: int = 0


@dataclass
class Plan:
    org: object = None
    to_create: list = field(default_factory=list)
    already_linked: list = field(default_factory=list)
    locations: dict = field(default_factory=dict)
    location_counts: dict = field(default_factory=dict)
    designations: dict = field(default_factory=dict)
    no_designation: int = 0
    devices: dict = field(default_factory=dict)
    flagged: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    seats_left: object = None


@dataclass
class ApplyResult:
    org: object = None
    org_created: bool = False
    projects_created: int = 0
    designations_created: int = 0
    devices_created: int = 0
    devices_remapped: int = 0
    users_created: int = 0
    identities_created: int = 0
    identities_linked: int = 0


def split_name(name):
    """First name = all but the last word, last name = the last word."""
    words = name.split()
    if len(words) == 1:
        return "", words[0]
    return " ".join(words[:-1]), words[-1]


def username_part(code):
    return re.sub(r"[^a-z0-9_-]", "", code.lower())


def make_username(org_id, code):
    return "sm%s-%s@%s" % (org_id, username_part(code), USERNAME_DOMAIN)


def placeholder_owner_email(org_name):
    """Email for a placeholder owner. Nobody can log in as it."""
    slug = re.sub(r"[^a-z0-9]+", "-", (org_name or "").lower()).strip("-") or "org"
    return "owner-%s@%s" % (slug[:60], USERNAME_DOMAIN)


def parse_csv(path, *, status="Working", skip_codes=()):
    skip = {str(c).strip().casefold() for c in skip_codes if str(c).strip()}
    want = (status or "").strip().casefold()
    result = ParseResult()
    try:
        handle = open(path, newline="", encoding="utf-8-sig")
    except OSError as exc:
        result.errors.append("Cannot open the CSV file (%s)." % exc.__class__.__name__)
        return result

    with handle:
        reader = csv.DictReader(handle)
        reader.fieldnames = [h.strip() for h in (reader.fieldnames or [])]
        missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
        if missing:
            result.errors.append("CSV is missing column(s): %s." % ", ".join(missing))
            return result

        first_line = {}
        for raw in reader:
            line = reader.line_num
            values = {
                k: (v.strip() if isinstance(v, str) else "")
                for k, v in raw.items()
                if k is not None
            }
            if not any(values.values()):
                continue
            result.total_rows += 1

            code = values.get("EmployeeCode", "")
            if code and code.casefold() in skip:
                result.skipped_codes += 1
                continue
            if values.get("Status", "").casefold() != want:
                result.skipped_status += 1
                continue
            if not code:
                result.errors.append("line %d: EmployeeCode is blank." % line)
                continue

            key = code.casefold()
            if key in first_line:
                result.errors.append(
                    "line %d (code %s): duplicate code, first seen on line %d."
                    % (line, code, first_line[key])
                )
                continue
            first_line[key] = line

            problems = []
            if len(code) > CODE_MAX:
                problems.append("code is longer than %d characters" % CODE_MAX)
            device_code = values.get("DeviceCode", "")
            if device_code and device_code != code:
                problems.append("EmployeeCode and DeviceCode differ")

            name = values.get("EmployeeName", "")
            if not name:
                problems.append("name is blank")
            else:
                first, last = split_name(name)
                if len(first) > NAME_PART_MAX or len(last) > NAME_PART_MAX:
                    problems.append("name is too long")

            location = values.get("Location", "")
            if not location:
                problems.append("Location is blank")

            designation = values.get("Designation", "")
            if designation.casefold() in NO_DESIGNATION:
                designation = ""
            if len(designation) > POSITION_MAX:
                problems.append("designation is longer than %d characters" % POSITION_MAX)

            doj = None
            if values.get("DOJ"):
                try:
                    doj = date.fromisoformat(values["DOJ"])
                except ValueError:
                    problems.append("DOJ is not a YYYY-MM-DD date")

            if problems:
                for problem in problems:
                    result.errors.append("line %d (code %s): %s." % (line, code, problem))
                continue

            flags = []
            if not code.isdigit():
                flags.append("non-numeric code")
            if any(values.get(c, "").casefold().startswith("default") for c in FLAG_COLUMNS):
                flags.append("default company/department/category")

            result.rows.append(
                Row(
                    line=line,
                    code=code,
                    name=name,
                    location=location,
                    designation=designation,
                    doj=doj,
                    flags=flags,
                )
            )
    return result


def check_new_org(*, name, owner_email=""):
    """Errors that would stop create_organization, found before any write."""
    User = get_user_model()
    errors = []
    name = (name or "").strip()
    if not name:
        errors.append("Organization name is required.")
    elif Organization.objects.filter(name__iexact=name).exists():
        errors.append("An organization with this name already exists.")
    owner_email = (owner_email or "").strip()
    if owner_email and User.objects.filter(email__iexact=owner_email).exists():
        errors.append("An account with the owner email already exists.")
    return errors


def build_plan(parsed, *, project_map, device_map, org=None):
    """Check everything and decide what would be written. Writes nothing."""
    User = get_user_model()
    plan = Plan(org=org)
    plan.errors.extend(parsed.errors)

    canon = {}
    for loc, code in project_map.items():
        loc_s = (loc or "").strip()
        code_s = (code or "").strip()
        if not loc_s:
            plan.errors.append("A --project has a blank Location.")
            continue
        if not PROJECT_CODE_RE.match(code_s):
            plan.errors.append(
                "Project code for Location '%s' is invalid "
                "(letters, digits, - and _, at most 20)." % loc_s
            )
            continue
        canon[loc_s.casefold()] = (loc_s, code_s.upper())

    by_code = {}
    for name, code in canon.values():
        by_code.setdefault(code, []).append(name)
    for code, names in by_code.items():
        if len(names) > 1:
            plan.errors.append("Project code %s is used for more than one Location." % code)

    missing_locations = {}
    for row in parsed.rows:
        if row.location.casefold() not in canon:
            missing_locations.setdefault(row.location.casefold(), row.location)
    for loc in missing_locations.values():
        plan.errors.append("Location '%s' has no --project mapping." % loc)

    linked = set()
    if org is not None:
        linked = set(
            BiometricIdentity.objects.filter(
                organization=org, employee__isnull=False
            ).values_list("device_code", flat=True)
        )
    for row in parsed.rows:
        if row.code in linked:
            plan.already_linked.append(row.code)
        else:
            plan.to_create.append(row)

    # Projects to make sure of: Locations in the CSV plus Locations of devices.
    for row in parsed.rows:
        entry = canon.get(row.location.casefold())
        if entry:
            plan.locations.setdefault(entry[0], entry[1])
    for serial, loc in device_map.items():
        serial_s = (serial or "").strip()
        loc_s = (loc or "").strip()
        if not serial_s:
            plan.errors.append("A --device has a blank serial number.")
            continue
        entry = canon.get(loc_s.casefold())
        if entry is None:
            plan.errors.append(
                "Device %s points to unknown Location '%s'." % (serial_s, loc_s)
            )
            continue
        plan.locations.setdefault(entry[0], entry[1])
        plan.devices[serial_s] = entry[0]

    for row in plan.to_create:
        entry = canon.get(row.location.casefold())
        if entry:
            plan.location_counts[entry[0].casefold()] = (
                plan.location_counts.get(entry[0].casefold(), 0) + 1
            )
        if row.designation:
            plan.designations.setdefault(row.designation.casefold(), row.designation)
        else:
            plan.no_designation += 1
        for flag in row.flags:
            plan.flagged.append((row.code, flag))

    seen_parts = {}
    for row in plan.to_create:
        part = username_part(row.code)
        if not part:
            plan.errors.append("line %d (code %s): code has no usable characters." % (row.line, row.code))
        elif part in seen_parts:
            plan.errors.append(
                "line %d (code %s): login name clashes with line %d."
                % (row.line, row.code, seen_parts[part])
            )
        else:
            seen_parts[part] = row.line

    if org is not None:
        wanted = [make_username(org.id, r.code) for r in plan.to_create if username_part(r.code)]
        taken = set(User.objects.filter(username__in=wanted).values_list("username", flat=True))
        for row in plan.to_create:
            if username_part(row.code) and make_username(org.id, row.code) in taken:
                plan.errors.append(
                    "line %d (code %s): a login for this code already exists." % (row.line, row.code)
                )

        used_names = set()
        for name, code in plan.locations.items():
            used_names.add(name)
            if Project.objects.filter(organization=org, name__iexact=name).exists():
                continue
            if Project.objects.filter(organization=org, code=code).exists():
                plan.errors.append("Project code %s is already used by another project." % code)

        plan.seats_left = seats_left(org)
        if plan.seats_left is not None and len(plan.to_create) > plan.seats_left:
            plan.errors.append(
                "Seat limit: %d people to add but only %d seats left."
                % (len(plan.to_create), plan.seats_left)
            )
    return plan


def _ensure_project(org, name, code, result):
    existing = Project.objects.filter(organization=org, name__iexact=name).order_by("id").first()
    if existing is not None:
        return existing
    if Project.objects.filter(organization=org, code=code.upper()).exists():
        raise ImporterError("Project code %s is already used by another project." % code)
    project = Project.objects.create(organization=org, name=name, code=code)
    result.projects_created += 1
    return project


def _ensure_designation(org, name, result):
    existing = (
        DesignationMaster.objects.filter(organization=org, name__iexact=name)
        .order_by("id")
        .first()
    )
    if existing is not None:
        return existing
    result.designations_created += 1
    return DesignationMaster.objects.create(organization=org, name=name)


def _ensure_device(org, serial, project, location_name, result):
    device, created = BiometricDevice.objects.get_or_create(
        organization=org,
        serial_number=serial,
        defaults={"name": location_name, "project": project},
    )
    if created:
        result.devices_created += 1
    elif device.project_id != project.id:
        device.project = project
        if not device.name:
            device.name = location_name
        device.save()
        result.devices_remapped += 1
    return device


def _link_identity(org, code, profile, result):
    identity, created = BiometricIdentity.objects.get_or_create(
        organization=org, device_code=code, defaults={"employee": profile}
    )
    if created:
        result.identities_created += 1
    elif identity.employee_id is None:
        identity.employee = profile
        identity.save(update_fields=["employee"])
        result.identities_linked += 1
    elif identity.employee_id != profile.id:
        raise ImporterError("A device code is already linked to a different employee.")
    return identity


def _create_person(org, row, project, designation, result):
    User = get_user_model()
    first, last = split_name(row.name)
    user = User(
        username=make_username(org.id, row.code),
        first_name=first,
        last_name=last,
        email="",
    )
    user.set_unusable_password()
    user._organization = org
    user.save()

    profile = empProfile.objects.filter(user=user).first()
    if profile is None or profile.organization_id != org.id:
        raise ImporterError("A profile was not created in the right organization.")
    profile.project = project
    profile.designation = designation
    profile.position = row.designation or None
    profile.date_hired = row.doj
    profile.is_active = True
    profile.save(
        update_fields=[
            "project",
            "designation",
            "position",
            "date_hired",
            "is_active",
            "updated_at",
        ]
    )
    result.users_created += 1
    _link_identity(org, row.code, profile, result)
    return profile


def apply_plan(plan, *, new_org=None):
    """Write the plan in ONE transaction. Any failure rolls back everything,
    including a newly created organization.

    new_org (only when plan.org is None) is a dict of the keyword arguments for
    app_organizations.services.create_organization.
    """
    if plan.errors:
        raise ImporterError("The plan has errors, so nothing was written.")

    result = ApplyResult()
    with transaction.atomic():
        org = plan.org
        if org is None:
            if not new_org:
                raise ImporterError("No organization to import into.")
            try:
                org, _owner = create_organization(**new_org)
            except ValueError as exc:
                raise ImporterError(str(exc)) from None
            result.org_created = True
        result.org = org

        left = seats_left(org)
        if left is not None and len(plan.to_create) > left:
            raise ImporterError(
                "Seat limit: %d people to add but only %d seats left."
                % (len(plan.to_create), left)
            )

        projects = {}
        for name, code in plan.locations.items():
            projects[name.casefold()] = _ensure_project(org, name, code, result)

        designations = {}
        for key, name in plan.designations.items():
            designations[key] = _ensure_designation(org, name, result)

        for serial, location in plan.devices.items():
            _ensure_device(org, serial, projects[location.casefold()], location, result)

        for row in plan.to_create:
            location_key = _location_key(plan, row)
            _create_person(
                org,
                row,
                projects[location_key],
                designations.get(row.designation.casefold()) if row.designation else None,
                result,
            )
    return result


def _location_key(plan, row):
    for name in plan.locations:
        if name.casefold() == row.location.casefold():
            return name.casefold()
    raise ImporterError("A person has a Location with no project.")
