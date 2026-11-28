"""Tests for the Smart Office employee importer (Patch B)."""
import csv
import os
import shutil
import tempfile
from datetime import date
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from app_biometric import importer
from app_biometric.models import BiometricDevice, BiometricIdentity, PunchLog
from app_organizations.entitlements import seats_left
from app_organizations.models import Organization, OrganizationMember
from app_organizations.services import create_organization
from app_projects.models import Project
from appEmp.models import DesignationMaster, empProfile

User = get_user_model()

HEADER = [
    "EmployeeCode", "EmployeeName", "DeviceCode", "Company", "Department",
    "Location", "Designation", "Grade", "Team", "Category", "EmploymentType",
    "Gender", "DOJ", "DOC", "DOB", "RFID", "UIDNo", "PANNo", "VoterIdNo",
    "Status", "DOR", "HolidayGroup", "ShiftGroupCode",
]
PROJECTS = {"Chakrawda Plaza": "CHK", "Bhuteda Plaza": "BHT", "Ujjain HO": "UJH"}
DEVICES = {"SER1": "Chakrawda Plaza", "SER2": "Bhuteda Plaza", "SER3": "Ujjain HO"}
NAMES = ["Ram Kumar Singh", "Mohan Lal", "Amit Verma", "Mohan", "Verma", "Singh"]


def row(code, name, location, designation="", doj="2024-04-01", status="Working", **extra):
    base = {h: "" for h in HEADER}
    base.update(
        EmployeeCode=code, EmployeeName=name, DeviceCode=code, Location=location,
        Designation=designation, DOJ=doj, Status=status,
        Company="UJTPL", Department="Toll", Category="GS",
    )
    base.update(extra)
    return base


class ImporterBase(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser("root", "root@x.com", "pw")
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def make_csv(self, rows, name="employees.csv", encoding="utf-8"):
        path = os.path.join(self.tmp, name)
        with open(path, "w", newline="", encoding=encoding) as handle:
            writer = csv.DictWriter(handle, fieldnames=HEADER)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def sample_rows(self):
        return [
            row("101", "Ram Kumar Singh", "Chakrawda Plaza", "Supervisor", "2024-04-01"),
            row("102", "Sita", "Chakrawda Plaza", "Driver", "2024-05-01"),
            row("103", "Mohan Lal", "Bhuteda Plaza", "None", "2024-06-01"),
            row("UJTPL62", "Amit Verma", "Ujjain HO", "supervisor", "2024-07-01"),
        ]

    def parse(self, rows, **kw):
        return importer.parse_csv(self.make_csv(rows), **kw)

    def plan(self, rows, org=None, projects=None, devices=None, **kw):
        parsed = self.parse(rows, **kw)
        return importer.build_plan(
            parsed,
            project_map=PROJECTS if projects is None else projects,
            device_map=DEVICES if devices is None else devices,
            org=org,
        )

    def make_org(self, name="Org A", email="a@x.com"):
        org, _owner = create_organization(
            name=name, owner_email=email, owner_first_name="A", created_by=self.root
        )
        return org

    def new_org_args(self, name="Toll Plaza"):
        return {
            "name": name,
            "owner_email": importer.placeholder_owner_email(name),
            "owner_first_name": "Placeholder",
            "owner_last_name": "Owner",
            "created_by": self.root,
        }

    def counts(self):
        return {
            "orgs": Organization.objects.count(),
            "users": User.objects.count(),
            "profiles": empProfile.objects.count(),
            "members": OrganizationMember.objects.count(),
            "projects": Project.objects.count(),
            "designations": DesignationMaster.objects.count(),
            "devices": BiometricDevice.objects.count(),
            "identities": BiometricIdentity.objects.count(),
        }

    def imported_profile(self, org, code):
        return BiometricIdentity.objects.get(organization=org, device_code=code).employee

    def cmd(self, rows, *extra, projects=None, devices=None):
        out = StringIO()
        args = ["--csv", self.make_csv(rows)]
        for loc, code in (PROJECTS if projects is None else projects).items():
            args += ["--project", "%s=%s" % (loc, code)]
        for serial, loc in (DEVICES if devices is None else devices).items():
            args += ["--device", "%s=%s" % (serial, loc)]
        args += list(extra)
        call_command("import_smartoffice_employees", *args, stdout=out)
        return out.getvalue()

    def flaky(self, fail_on=3):
        real = importer._create_person
        state = {"calls": 0}

        def wrapper(*args, **kwargs):
            state["calls"] += 1
            if state["calls"] == fail_on:
                raise RuntimeError("boom")
            return real(*args, **kwargs)

        return wrapper, state


class ParseTests(ImporterBase):
    def test_reads_rows_and_fields(self):
        parsed = self.parse(self.sample_rows())
        self.assertEqual(parsed.errors, [])
        self.assertEqual([r.code for r in parsed.rows], ["101", "102", "103", "UJTPL62"])
        first = parsed.rows[0]
        self.assertEqual(first.name, "Ram Kumar Singh")
        self.assertEqual(first.location, "Chakrawda Plaza")
        self.assertEqual(first.designation, "Supervisor")
        self.assertEqual(first.doj, date(2024, 4, 1))

    def test_blank_designation_markers_mean_none(self):
        rows = [
            row(str(i), "P Q", "Ujjain HO", marker)
            for i, marker in enumerate(["", "None", "null", "-", "NONE"], start=1)
        ]
        parsed = self.parse(rows)
        self.assertEqual([r.designation for r in parsed.rows], [""] * 5)

    def test_status_filter_and_skip_code(self):
        rows = self.sample_rows() + [
            row("TestEmployee1", "T U", "Ujjain HO"),
            row("500", "R S", "Ujjain HO", status="Resigned"),
        ]
        parsed = self.parse(rows, skip_codes=["testemployee1"])
        self.assertEqual(parsed.skipped_codes, 1)
        self.assertEqual(parsed.skipped_status, 1)
        self.assertEqual(len(parsed.rows), 4)
        self.assertEqual(parsed.errors, [])

    def test_status_option_is_case_insensitive_and_changeable(self):
        rows = [row("1", "A B", "Ujjain HO", status="working"), row("2", "C D", "Ujjain HO", status="Resigned")]
        self.assertEqual([r.code for r in self.parse(rows).rows], ["1"])
        self.assertEqual([r.code for r in self.parse(rows, status="Resigned").rows], ["2"])

    def test_flags(self):
        rows = [
            row("101", "A B", "Ujjain HO"),
            row("Trainee01", "C D", "Ujjain HO"),
            row("249", "E F", "Ujjain HO", Company="DefaultCompany"),
            row("259", "G H", "Ujjain HO", Department="DefaultDepartment"),
            row("285", "I J", "Ujjain HO", Category="DefaultCategory"),
        ]
        flags = {r.code: r.flags for r in self.parse(rows).rows}
        self.assertEqual(flags["101"], [])
        self.assertEqual(flags["Trainee01"], ["non-numeric code"])
        for code in ("249", "259", "285"):
            self.assertEqual(flags[code], ["default company/department/category"])

    def errors_for(self, rows):
        parsed = self.parse(rows)
        self.assertEqual(parsed.rows, [])
        return parsed.errors

    def test_blank_code(self):
        errors = self.errors_for([row("", "Some Person", "Ujjain HO")])
        self.assertEqual(len(errors), 1)
        self.assertIn("EmployeeCode is blank", errors[0])

    def test_duplicate_code_is_case_insensitive(self):
        parsed = self.parse([row("ab1", "A B", "Ujjain HO"), row("AB1", "C D", "Ujjain HO")])
        self.assertEqual(len(parsed.rows), 1)
        self.assertEqual(len(parsed.errors), 1)
        self.assertIn("duplicate code", parsed.errors[0])

    def test_blank_name(self):
        errors = self.errors_for([row("101", "", "Ujjain HO")])
        self.assertIn("name is blank", errors[0])

    def test_bad_date(self):
        errors = self.errors_for([row("101", "A B", "Ujjain HO", doj="01/04/2024")])
        self.assertIn("DOJ", errors[0])

    def test_blank_location(self):
        errors = self.errors_for([row("101", "A B", "")])
        self.assertIn("Location is blank", errors[0])

    def test_code_and_device_code_differ(self):
        errors = self.errors_for([row("101", "A B", "Ujjain HO", DeviceCode="202")])
        self.assertIn("differ", errors[0])

    def test_long_designation_and_long_code(self):
        errors = self.errors_for([row("101", "A B", "Ujjain HO", "x" * 51)])
        self.assertIn("designation is longer", errors[0])
        errors = self.errors_for([row("c" * 65, "A B", "Ujjain HO")])
        self.assertIn("longer than 64", errors[0])

    def test_missing_column_and_bad_path(self):
        path = os.path.join(self.tmp, "bad.csv")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("EmployeeCode,EmployeeName\n101,A B\n")
        parsed = importer.parse_csv(path)
        self.assertTrue(any("missing column" in e for e in parsed.errors))
        parsed = importer.parse_csv(os.path.join(self.tmp, "nope.csv"))
        self.assertTrue(any("Cannot open" in e for e in parsed.errors))

    def test_file_with_bom_is_read(self):
        path = self.make_csv(self.sample_rows(), encoding="utf-8-sig")
        parsed = importer.parse_csv(path)
        self.assertEqual(parsed.errors, [])
        self.assertEqual(len(parsed.rows), 4)

    def test_name_split_and_helpers(self):
        self.assertEqual(importer.split_name("Sita"), ("", "Sita"))
        self.assertEqual(importer.split_name("A B"), ("A", "B"))
        self.assertEqual(importer.split_name("A B  C"), ("A B", "C"))
        self.assertEqual(importer.make_username(5, "UJTPL62"), "sm5-ujtpl62@smartoffice.invalid")
        self.assertEqual(importer.make_username(5, "Trainee 01"), "sm5-trainee01@smartoffice.invalid")
        self.assertEqual(
            importer.placeholder_owner_email("Toll Plaza"), "owner-toll-plaza@smartoffice.invalid"
        )


class PlanTests(ImporterBase):
    def assertError(self, plan, text):
        self.assertTrue(any(text in e for e in plan.errors), plan.errors)

    def test_clean_plan(self):
        plan = self.plan(self.sample_rows())
        self.assertEqual(plan.errors, [])
        self.assertEqual(len(plan.to_create), 4)
        self.assertEqual(plan.locations, PROJECTS)
        self.assertEqual(
            plan.location_counts, {"chakrawda plaza": 2, "bhuteda plaza": 1, "ujjain ho": 1}
        )
        self.assertEqual(set(plan.designations), {"supervisor", "driver"})
        self.assertEqual(plan.no_designation, 1)
        self.assertEqual(plan.devices, DEVICES)

    def test_project_codes_are_upper_cased(self):
        projects = {"Chakrawda Plaza": "chk", "Bhuteda Plaza": "bht", "Ujjain HO": "ujh"}
        plan = self.plan(self.sample_rows(), projects=projects)
        self.assertEqual(plan.errors, [])
        self.assertEqual(plan.locations, PROJECTS)

    def test_location_without_project_mapping(self):
        projects = {"Chakrawda Plaza": "CHK", "Bhuteda Plaza": "BHT"}
        plan = self.plan(self.sample_rows(), projects=projects, devices={})
        self.assertError(plan, "Ujjain HO")
        self.assertError(plan, "no --project mapping")

    def test_bad_project_codes(self):
        projects = dict(PROJECTS, **{"Chakrawda Plaza": "BAD CODE!"})
        self.assertError(self.plan(self.sample_rows(), projects=projects), "invalid")
        projects = dict(PROJECTS, **{"Chakrawda Plaza": "X" * 21})
        self.assertError(self.plan(self.sample_rows(), projects=projects), "invalid")

    def test_duplicate_project_codes(self):
        projects = dict(PROJECTS, **{"Bhuteda Plaza": "chk"})
        self.assertError(self.plan(self.sample_rows(), projects=projects), "more than one Location")

    def test_device_problems(self):
        plan = self.plan(self.sample_rows(), devices={"SER1": "Atlantis"})
        self.assertError(plan, "unknown Location")
        plan = self.plan(self.sample_rows(), devices={"": "Ujjain HO"})
        self.assertError(plan, "blank serial")

    def test_login_name_clash_and_unusable_code(self):
        rows = [row("A.1", "P Q", "Ujjain HO"), row("A1", "R S", "Ujjain HO")]
        self.assertError(self.plan(rows), "login name clashes")
        self.assertError(self.plan([row("...", "P Q", "Ujjain HO")]), "no usable characters")

    def test_parse_errors_stop_the_plan(self):
        plan = self.plan([row("101", "", "Ujjain HO")])
        self.assertTrue(plan.errors)

    def test_error_messages_never_contain_names(self):
        rows = [
            row("1", "Zed Hidden", "Ujjain HO"),
            row("1", "Yan Hidden", "Ujjain HO"),
            row("2", "Xan Hidden", "Ujjain HO", doj="bad"),
            row("3", "Wes Hidden", "Nowhere"),
        ]
        plan = self.plan(rows, devices={})
        self.assertTrue(plan.errors)
        self.assertTrue(all("Hidden" not in e for e in plan.errors), plan.errors)

    def test_check_new_org(self):
        self.make_org("Org A", "a@x.com")
        self.assertTrue(importer.check_new_org(name="org a"))
        self.assertTrue(importer.check_new_org(name="New Org", owner_email="A@X.COM"))
        self.assertTrue(importer.check_new_org(name=""))
        self.assertEqual(importer.check_new_org(name="New Org", owner_email="n@x.com"), [])

    def test_existing_org_project_code_used_by_another_project(self):
        org = self.make_org()
        Project.objects.create(organization=org, name="Other Site", code="CHK")
        self.assertError(self.plan(self.sample_rows(), org=org), "already used by another project")

    def test_existing_org_login_already_exists(self):
        org = self.make_org()
        User.objects.create(username="sm%d-101@smartoffice.invalid" % org.id)
        self.assertError(self.plan(self.sample_rows(), org=org), "login for this code already exists")


class ApplyNewOrgTests(ImporterBase):
    def test_apply_creates_everything(self):
        plan = self.plan(self.sample_rows())
        self.assertEqual(plan.errors, [])
        result = importer.apply_plan(plan, new_org=self.new_org_args())
        org = result.org

        self.assertTrue(result.org_created)
        self.assertEqual(org.name, "Toll Plaza")
        self.assertEqual(result.users_created, 4)
        self.assertEqual(result.projects_created, 3)
        self.assertEqual(
            dict(Project.objects.filter(organization=org).values_list("name", "code")), PROJECTS
        )
        self.assertLessEqual(result.designations_created, 2)
        for name in ("Supervisor", "Driver"):
            self.assertEqual(
                DesignationMaster.objects.filter(organization=org, name__iexact=name).count(), 1
            )

        owner = OrganizationMember.objects.get(organization=org, role="owner").user
        self.assertEqual(owner.email, importer.placeholder_owner_email("Toll Plaza"))
        self.assertFalse(owner.has_usable_password())
        self.assertEqual(OrganizationMember.objects.filter(organization=org, role="member").count(), 4)

        profile = self.imported_profile(org, "101")
        user = profile.user
        self.assertEqual(user.username, "sm%d-101@smartoffice.invalid" % org.id)
        self.assertEqual(user.email, "")
        self.assertFalse(user.has_usable_password())
        self.assertEqual((user.first_name, user.last_name), ("Ram Kumar", "Singh"))
        self.assertEqual(profile.organization_id, org.id)
        self.assertEqual(profile.project.name, "Chakrawda Plaza")
        self.assertEqual(profile.designation.name, "Supervisor")
        self.assertEqual(profile.position, "Supervisor")
        self.assertEqual(profile.date_hired, date(2024, 4, 1))
        self.assertTrue(profile.is_active)

        one_word = self.imported_profile(org, "102").user
        self.assertEqual((one_word.first_name, one_word.last_name), ("", "Sita"))

        no_designation = self.imported_profile(org, "103")
        self.assertIsNone(no_designation.designation)
        self.assertIsNone(no_designation.position)

        other = self.imported_profile(org, "UJTPL62")
        self.assertEqual(other.user.username, "sm%d-ujtpl62@smartoffice.invalid" % org.id)
        self.assertEqual(other.designation_id, profile.designation_id)

        for serial, location in DEVICES.items():
            device = BiometricDevice.objects.get(organization=org, serial_number=serial)
            self.assertEqual(device.project.name, location)
        identities = BiometricIdentity.objects.filter(organization=org)
        self.assertEqual(identities.count(), 4)
        self.assertEqual(identities.filter(employee__isnull=True).count(), 0)

    def test_plan_with_errors_is_refused(self):
        plan = self.plan([row("101", "", "Ujjain HO")])
        before = self.counts()
        with self.assertRaises(importer.ImporterError):
            importer.apply_plan(plan, new_org=self.new_org_args())
        self.assertEqual(before, self.counts())

    def test_no_organization_given(self):
        plan = self.plan(self.sample_rows())
        with self.assertRaises(importer.ImporterError):
            importer.apply_plan(plan)

    def test_org_name_taken_writes_nothing(self):
        self.make_org("Toll Plaza", "t@x.com")
        plan = self.plan(self.sample_rows())
        before = self.counts()
        with self.assertRaises(importer.ImporterError):
            importer.apply_plan(plan, new_org=self.new_org_args("Toll Plaza"))
        self.assertEqual(before, self.counts())


class ExistingOrgTests(ImporterBase):
    def apply(self, org, rows=None):
        plan = self.plan(rows or self.sample_rows(), org=org)
        self.assertEqual(plan.errors, [])
        return importer.apply_plan(plan)

    def test_import_into_existing_org(self):
        org = self.make_org()
        result = self.apply(org)
        self.assertFalse(result.org_created)
        self.assertEqual(result.users_created, 4)
        self.assertEqual(self.imported_profile(org, "103").organization_id, org.id)

    def test_rerun_creates_nothing(self):
        org = self.make_org()
        self.apply(org)
        before = self.counts()
        plan = self.plan(self.sample_rows(), org=org)
        self.assertEqual(plan.errors, [])
        self.assertEqual(plan.to_create, [])
        self.assertEqual(len(plan.already_linked), 4)
        result = importer.apply_plan(plan)
        self.assertEqual(
            (result.users_created, result.projects_created, result.devices_created,
             result.identities_created, result.identities_linked),
            (0, 0, 0, 0, 0),
        )
        self.assertEqual(before, self.counts())

    def test_rerun_adds_only_new_people(self):
        org = self.make_org()
        self.apply(org)
        rows = self.sample_rows() + [row("105", "New Person", "Ujjain HO", "Driver")]
        plan = self.plan(rows, org=org)
        self.assertEqual([r.code for r in plan.to_create], ["105"])
        result = importer.apply_plan(plan)
        self.assertEqual(result.users_created, 1)
        self.assertEqual(result.projects_created, 0)

    def test_hr_edits_survive_a_rerun(self):
        org = self.make_org()
        self.apply(org)
        profile = self.imported_profile(org, "101")
        boss = DesignationMaster.objects.create(organization=org, name="Boss")
        hq = Project.objects.create(organization=org, name="HQ", code="HQ")
        profile.designation = boss
        profile.position = "Boss"
        profile.project = hq
        profile.is_active = False
        profile.date_hired = date(2020, 1, 1)
        profile.save()
        profile.user.first_name = "Edited"
        profile.user.save()

        plan = self.plan(self.sample_rows(), org=org)
        self.assertEqual(plan.to_create, [])
        importer.apply_plan(plan)

        profile = self.imported_profile(org, "101")
        self.assertEqual(profile.designation_id, boss.id)
        self.assertEqual(profile.position, "Boss")
        self.assertEqual(profile.project_id, hq.id)
        self.assertFalse(profile.is_active)
        self.assertEqual(profile.date_hired, date(2020, 1, 1))
        self.assertEqual(profile.user.first_name, "Edited")

    def test_punches_synced_before_import_get_linked(self):
        org = self.make_org()
        device = BiometricDevice.objects.create(organization=org, serial_number="SER1", name="old")
        for code in ("101", "102", "999"):
            BiometricIdentity.objects.create(organization=org, device_code=code)
        PunchLog.objects.create(
            organization=org, device=device, employee_code="101", punch_time=timezone.now()
        )

        result = self.apply(org)

        self.assertEqual(result.identities_linked, 2)
        self.assertEqual(result.identities_created, 2)
        self.assertEqual(result.devices_created, 2)
        self.assertEqual(result.devices_remapped, 1)
        self.assertIsNotNone(self.imported_profile(org, "101"))
        self.assertIsNotNone(self.imported_profile(org, "102"))
        self.assertIsNone(self.imported_profile(org, "999"))
        self.assertEqual(BiometricIdentity.objects.filter(organization=org).count(), 5)
        self.assertEqual(PunchLog.objects.filter(organization=org).count(), 1)
        device.refresh_from_db()
        self.assertEqual(device.project.name, "Chakrawda Plaza")

    def test_same_name_project_is_reused(self):
        org = self.make_org()
        existing = Project.objects.create(organization=org, name="chakrawda plaza", code="ZZZ")
        result = self.apply(org)
        self.assertEqual(result.projects_created, 2)
        self.assertEqual(self.imported_profile(org, "101").project_id, existing.id)
        self.assertEqual(
            Project.objects.filter(organization=org, name__iexact="chakrawda plaza").count(), 1
        )

    def active_seats(self, org):
        return empProfile.objects.filter(organization=org, is_active=True).count()

    def test_seat_limit_blocks_the_plan(self):
        org = self.make_org()
        org.max_employees = self.active_seats(org) + 2
        org.save()
        plan = self.plan(self.sample_rows(), org=org)
        self.assertTrue(any("Seat limit" in e for e in plan.errors), plan.errors)
        before = self.counts()
        with self.assertRaises(importer.ImporterError):
            importer.apply_plan(plan)
        self.assertEqual(before, self.counts())

    def test_seat_limit_exact_fit_is_allowed(self):
        org = self.make_org()
        org.max_employees = self.active_seats(org) + 4
        org.save()
        self.apply(org)
        self.assertEqual(seats_left(org), 0)

    def test_seat_limit_lowered_after_planning(self):
        org = self.make_org()
        plan = self.plan(self.sample_rows(), org=org)
        self.assertEqual(plan.errors, [])
        org.max_employees = self.active_seats(org)
        org.save()
        before = self.counts()
        with self.assertRaises(importer.ImporterError):
            importer.apply_plan(plan)
        self.assertEqual(before, self.counts())


class RollbackTests(ImporterBase):
    def test_failure_midway_rolls_back_the_new_org_too(self):
        plan = self.plan(self.sample_rows())
        before = self.counts()
        wrapper, state = self.flaky(fail_on=3)
        with mock.patch.object(importer, "_create_person", wrapper):
            with self.assertRaises(RuntimeError):
                importer.apply_plan(plan, new_org=self.new_org_args())
        self.assertEqual(state["calls"], 3)
        self.assertEqual(before, self.counts())
        self.assertFalse(Organization.objects.filter(name="Toll Plaza").exists())

    def test_failure_midway_rolls_back_in_an_existing_org(self):
        org = self.make_org()
        plan = self.plan(self.sample_rows(), org=org)
        before = self.counts()
        wrapper, _state = self.flaky(fail_on=3)
        with mock.patch.object(importer, "_create_person", wrapper):
            with self.assertRaises(RuntimeError):
                importer.apply_plan(plan)
        self.assertEqual(before, self.counts())


class CommandTests(ImporterBase):
    NEW = ("--org-name", "Toll Plaza", "--created-by", "root")

    def test_dry_run_writes_nothing_and_hides_names(self):
        before = self.counts()
        out = self.cmd(self.sample_rows(), *self.NEW)
        self.assertEqual(before, self.counts())
        self.assertIn("DRY RUN", out)
        self.assertIn("Dry run only", out)
        self.assertIn("People to create: 4", out)
        self.assertIn("Chakrawda Plaza -> CHK (2 people to create)", out)
        self.assertIn("Supervisor", out)
        self.assertIn("UJTPL62: non-numeric code", out)
        self.assertIn("placeholder account that cannot log in", out)
        for name in NAMES:
            self.assertNotIn(name, out)
        self.assertNotIn("smartoffice.invalid", out)

    def test_dry_run_with_errors_fails_and_writes_nothing(self):
        before = self.counts()
        projects = {"Chakrawda Plaza": "CHK", "Bhuteda Plaza": "BHT"}
        with self.assertRaises(CommandError):
            self.cmd(self.sample_rows(), *self.NEW, projects=projects, devices={})
        self.assertEqual(before, self.counts())

    def test_commit_into_a_new_org_with_placeholder_owner(self):
        out = self.cmd(self.sample_rows(), *self.NEW, "--commit")
        self.assertIn("Import committed", out)
        self.assertIn("People created: 4", out)
        org = Organization.objects.get(name="Toll Plaza")
        self.assertEqual(Project.objects.filter(organization=org, code__in=PROJECTS.values()).count(), 3)
        self.assertEqual(
            empProfile.objects.filter(organization=org, user__username__endswith="@smartoffice.invalid").count(),
            5,
        )

    def test_commit_into_existing_org_by_id(self):
        org = self.make_org()
        out = self.cmd(self.sample_rows(), "--org-id", str(org.id), "--commit")
        self.assertIn("People created: 4", out)
        self.assertIsNotNone(self.imported_profile(org, "101"))

    def test_commit_needs_created_by_for_a_new_org(self):
        before = self.counts()
        with self.assertRaises(CommandError):
            self.cmd(self.sample_rows(), "--org-name", "Toll Plaza", "--commit")
        self.assertEqual(before, self.counts())

    def test_unknown_created_by_user(self):
        before = self.counts()
        with self.assertRaises(CommandError):
            self.cmd(self.sample_rows(), "--org-name", "Toll Plaza", "--created-by", "nobody", "--commit")
        self.assertEqual(before, self.counts())

    def test_org_options_are_checked(self):
        org = self.make_org()
        with self.assertRaises(CommandError):
            self.cmd(self.sample_rows(), "--org-id", str(org.id), "--org-name", "Other")
        with self.assertRaises(CommandError):
            self.cmd(self.sample_rows())
        with self.assertRaises(CommandError):
            self.cmd(self.sample_rows(), "--org-id", "999999")

    def test_malformed_project_and_device_arguments(self):
        out = StringIO()
        path = self.make_csv(self.sample_rows())
        with self.assertRaises(CommandError):
            call_command(
                "import_smartoffice_employees", "--csv", path, "--project", "NoEquals",
                *self.NEW, stdout=out
            )
        with self.assertRaises(CommandError):
            call_command(
                "import_smartoffice_employees", "--csv", path, "--device", "NoEquals",
                *self.NEW, stdout=out
            )

    def test_failed_commit_is_rolled_back_and_reports_only_the_error_class(self):
        before = self.counts()
        wrapper, _state = self.flaky(fail_on=2)
        with mock.patch.object(importer, "_create_person", wrapper):
            with self.assertRaises(CommandError) as ctx:
                self.cmd(self.sample_rows(), *self.NEW, "--commit")
        self.assertIn("rolled back", str(ctx.exception))
        self.assertIn("RuntimeError", str(ctx.exception))
        self.assertEqual(before, self.counts())
