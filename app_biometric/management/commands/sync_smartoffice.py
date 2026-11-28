from datetime import datetime, timedelta

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from app_biometric import services
from app_biometric.models import SyncRun


def _parse_date(value, label):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise CommandError(f"{label} must look like YYYY-MM-DD")


class Command(BaseCommand):
    help = (
        "Pull punches from Smart Office into PunchLog. Without --from it syncs "
        "yesterday and today (for the scheduled job). With --from it backfills "
        "in weekly chunks. Safe to re-run: duplicates are ignored. "
        "Prints counts only."
    )

    def add_arguments(self, parser):
        parser.add_argument("--org-id", type=int, required=True)
        parser.add_argument("--from", dest="from_date", help="YYYY-MM-DD (backfill)")
        parser.add_argument("--to", dest="to_date", help="YYYY-MM-DD (default today)")
        parser.add_argument("--chunk-days", type=int, default=7)
        parser.add_argument(
            "--retries",
            type=int,
            default=4,
            help="Retries per weekly call on network errors, 5xx or 429.",
        )
        parser.add_argument(
            "--retry-delay",
            type=float,
            default=2.0,
            help="Seconds before the first retry; doubles each time.",
        )
        parser.add_argument(
            "--pause",
            type=float,
            default=1.0,
            help="Seconds to wait between weekly calls.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and count only; write nothing to the database.",
        )

    def handle(self, *args, **opts):
        Organization = apps.get_model("app_organizations", "Organization")
        try:
            org = Organization.objects.get(pk=opts["org_id"])
        except Organization.DoesNotExist:
            raise CommandError("No organization with that id.")

        api_key = getattr(settings, "SMARTOFFICE_API_KEY", "")
        if not api_key:
            raise CommandError(
                "SMARTOFFICE_API_KEY is not set in the environment file."
            )

        today = timezone.localdate()
        if opts["from_date"]:
            mode = SyncRun.MODE_RANGE
            from_date = _parse_date(opts["from_date"], "--from")
        else:
            mode = SyncRun.MODE_DAILY
            from_date = today - timedelta(days=1)
        to_date = _parse_date(opts["to_date"], "--to") if opts["to_date"] else today
        if from_date > to_date:
            raise CommandError("--from must not be after --to")
        if opts["chunk_days"] < 2:
            raise CommandError("--chunk-days must be at least 2")
        if opts["retries"] < 0 or opts["retry_delay"] < 0 or opts["pause"] < 0:
            raise CommandError(
                "--retries, --retry-delay and --pause must not be negative"
            )

        self.stdout.write(
            f"Organization id={org.pk} | {from_date} to {to_date} | "
            f"{mode} | API key: set"
        )
        progress = self.stdout.write
        try:
            if opts["dry_run"]:
                totals = services.dry_run_range(
                    from_date,
                    to_date,
                    api_key,
                    chunk_days=opts["chunk_days"],
                    progress=progress,
                    retries=opts["retries"],
                    retry_delay=opts["retry_delay"],
                    pause=opts["pause"],
                )
                self.stdout.write(
                    "DRY RUN, nothing written. "
                    + ", ".join(f"{k} {v}" for k, v in totals.items())
                )
                return
            run = services.sync_range(
                org,
                from_date,
                to_date,
                mode,
                api_key,
                chunk_days=opts["chunk_days"],
                progress=progress,
                retries=opts["retries"],
                retry_delay=opts["retry_delay"],
                pause=opts["pause"],
            )
        except services.SmartOfficeError as exc:
            raise CommandError(str(exc))
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. calls {run.api_calls}, fetched {run.records_fetched}, "
                f"new {run.records_new}, skipped {run.records_skipped}"
            )
        )
