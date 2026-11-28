"""Import Smart Office employees (from "Export Employee Details") into an
organization and link them to their biometric codes.

Dry run by default: prints counts, Location names, designation names and
flagged codes only, never employee names or logins. Add --commit to write,
all in one transaction.
"""
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from app_biometric import importer
from app_organizations.models import Organization

MAX_ERROR_LINES = 40


class Command(BaseCommand):
    help = "Import Smart Office employees and link their biometric codes (dry run unless --commit)."

    def add_arguments(self, parser):
        parser.add_argument("--csv", required=True, help="Path to the employee CSV export.")
        parser.add_argument(
            "--project", action="append", default=[], metavar="LOCATION=CODE",
            help="Project code for a Location. Repeat for each Location.",
        )
        parser.add_argument(
            "--device", action="append", default=[], metavar="SERIAL=LOCATION",
            help="Device serial and the Location it belongs to. Repeatable.",
        )
        parser.add_argument(
            "--skip-code", action="append", default=[],
            help="EmployeeCode to leave out. Repeatable.",
        )
        parser.add_argument("--status", default="Working", help="Only import rows with this Status.")
        parser.add_argument("--org-id", type=int, help="Import into this existing organization.")
        parser.add_argument("--org-name", help="Create a new organization with this name.")
        parser.add_argument(
            "--owner-email",
            help="New organization: owner email (no account yet). Optional: a placeholder owner is used if left out.",
        )
        parser.add_argument(
            "--owner-first-name",
            help="New organization: owner first name. Optional with the placeholder owner.",
        )
        parser.add_argument("--owner-last-name", default="", help="New organization: owner last name.")
        parser.add_argument("--created-by", help="New organization: username of the creating user.")
        parser.add_argument("--commit", action="store_true", help="Write to the database.")

    def handle(self, *args, **opts):
        commit = opts["commit"]
        project_map = self._project_map(opts["project"])
        device_map = self._device_map(opts["device"])
        org = self._existing_org(opts)

        parsed = importer.parse_csv(
            os.path.expanduser(opts["csv"]),
            status=opts["status"],
            skip_codes=opts["skip_code"],
        )
        plan = importer.build_plan(
            parsed, project_map=project_map, device_map=device_map, org=org
        )

        new_org = None
        if org is None:
            plan.errors.extend(
                importer.check_new_org(
                    name=opts["org_name"],
                    owner_email=opts["owner_email"]
                    or importer.placeholder_owner_email(opts["org_name"]),
                )
            )
            if commit:
                new_org = self._new_org_args(opts, plan)

        self._report(plan, parsed, org, opts, commit)

        if plan.errors:
            raise CommandError("%d error(s) found. Nothing was written." % len(plan.errors))
        if not commit:
            self.stdout.write("Dry run only. Nothing was written. Add --commit to write.")
            return

        try:
            result = importer.apply_plan(plan, new_org=new_org)
        except importer.ImporterError as exc:
            raise CommandError("%s Everything was rolled back." % exc) from None
        except Exception as exc:
            raise CommandError(
                "Import failed and was rolled back (%s)." % exc.__class__.__name__
            ) from None
        self._report_result(result)

    def _project_map(self, values):
        mapping = {}
        seen = set()
        for value in values:
            if "=" not in value:
                raise CommandError("--project must look like 'Location=CODE'.")
            loc, code = value.rsplit("=", 1)
            loc = loc.strip()
            if loc.casefold() in seen:
                raise CommandError("--project is given twice for Location '%s'." % loc)
            seen.add(loc.casefold())
            mapping[loc] = code.strip()
        return mapping

    def _device_map(self, values):
        mapping = {}
        for value in values:
            if "=" not in value:
                raise CommandError("--device must look like 'SERIAL=Location'.")
            serial, loc = value.split("=", 1)
            serial = serial.strip()
            if serial in mapping:
                raise CommandError("--device is given twice for serial %s." % serial)
            mapping[serial] = loc.strip()
        return mapping

    def _existing_org(self, opts):
        new_keys = ("org_name", "owner_email", "owner_first_name", "created_by")
        if opts["org_id"] is not None:
            if any(opts[k] for k in new_keys) or opts["owner_last_name"]:
                raise CommandError("--org-id cannot be combined with new-organization options.")
            org = Organization.objects.filter(pk=opts["org_id"]).first()
            if org is None:
                raise CommandError("No organization with that id.")
            return org
        if not opts["org_name"]:
            raise CommandError("Give --org-id, or --org-name to create a new organization.")
        return None

    def _new_org_args(self, opts, plan):
        if not opts["created_by"]:
            plan.errors.append("--created-by is required with --commit for a new organization.")
            return None
        User = get_user_model()
        creator = User.objects.filter(username=opts["created_by"]).first()
        if creator is None:
            plan.errors.append("--created-by user was not found.")
            return None
        return {
            "name": opts["org_name"],
            "owner_email": opts["owner_email"]
            or importer.placeholder_owner_email(opts["org_name"]),
            "owner_first_name": opts["owner_first_name"] or "Placeholder",
            "owner_last_name": opts["owner_last_name"] or "Owner",
            "created_by": creator,
        }

    def _report(self, plan, parsed, org, opts, commit):
        w = self.stdout.write
        w("Smart Office employee import: %s" % ("COMMIT" if commit else "DRY RUN (nothing is written)"))
        w(
            "CSV: %d data rows read, %d skipped by status, %d skipped by --skip-code."
            % (parsed.total_rows, parsed.skipped_status, parsed.skipped_codes)
        )
        if org is not None:
            w("Organization: existing, id %s (%s)." % (org.id, org.name))
        else:
            w('Organization: NEW "%s".' % (opts["org_name"] or "").strip())
            w(
                "Owner: %s."
                % (
                    "as given"
                    if opts["owner_email"]
                    else "placeholder account that cannot log in"
                )
            )
        w(
            "People to create: %d. Already linked and skipped: %d."
            % (len(plan.to_create), len(plan.already_linked))
        )
        if plan.seats_left is not None:
            w("Seats left under the plan limit: %d." % plan.seats_left)
        w("Projects (one per Location):")
        for name, code in plan.locations.items():
            count = plan.location_counts.get(name.casefold(), 0)
            w("  %s -> %s (%d people to create)" % (name, code, count))
        names = sorted(plan.designations.values(), key=str.casefold)
        w("Designations (%d): %s" % (len(names), ", ".join(names) if names else "none"))
        w("People with no designation: %d." % plan.no_designation)
        w("Devices:")
        for serial, loc in plan.devices.items():
            w("  %s -> %s" % (serial, loc))
        if plan.flagged:
            w("Flagged codes (still imported):")
            for code, reason in plan.flagged:
                w("  %s: %s" % (code, reason))
        if plan.errors:
            w("Errors (%d), nothing will be written:" % len(plan.errors))
            for message in plan.errors[:MAX_ERROR_LINES]:
                w("  - %s" % message)
            if len(plan.errors) > MAX_ERROR_LINES:
                w("  ...and %d more." % (len(plan.errors) - MAX_ERROR_LINES))

    def _report_result(self, result):
        w = self.stdout.write
        w("Import committed.")
        w(
            "Organization id %s (%s)."
            % (result.org.id, "created" if result.org_created else "existing")
        )
        w("Projects created: %d." % result.projects_created)
        w("Designations created: %d." % result.designations_created)
        w(
            "Devices created: %d, remapped: %d."
            % (result.devices_created, result.devices_remapped)
        )
        w("People created: %d." % result.users_created)
        w(
            "Biometric identities created: %d, linked from earlier syncs: %d."
            % (result.identities_created, result.identities_linked)
        )
