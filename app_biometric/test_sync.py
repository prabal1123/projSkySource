"""Tests for app_biometric (Patch A). No network: every Smart Office call is mocked."""
from datetime import date, datetime, timedelta, timezone as dt_tz
from io import StringIO
from unittest import mock
from urllib import error

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from app_biometric import services
from app_biometric.models import (
    BiometricDevice,
    BiometricIdentity,
    PunchLog,
    SyncRun,
)

KEY = "TESTKEY-abc123"


def make_user(tag):
    return get_user_model().objects.create_user(
        username=f"{tag}@example.com",
        email=f"{tag}@example.com",
        password="Test-pass-12345",
    )


def make_org(name="Org A"):
    from app_organizations.models import Organization

    return Organization.objects.create(
        name=name, created_by=make_user(name.replace(" ", "").lower())
    )


def make_project(org, code):
    from app_projects.models import Project

    return Project.objects.create(organization=org, name=code, code=code)


def make_profile(org, tag):
    from appEmp.models import empProfile

    profile, _ = empProfile.objects.update_or_create(
        user=make_user(tag), defaults={"organization": org}
    )
    return profile


def rec(code="104", when="2026-11-25 09:01:02", serial="DEV1", direction=""):
    return {
        "EmployeeCode": code,
        "LogDate": when,
        "SerialNumber": serial,
        "PunchDirection": direction,
        "Temperature": 0,
        "TemperatureState": "Not Measured",
    }


def fake_response(text):
    cm = mock.MagicMock()
    cm.__enter__.return_value.read.return_value = text.encode("utf-8")
    return cm


class ParseRecordTests(SimpleTestCase):
    def test_valid_record_becomes_aware_ist_time(self):
        code, serial, when, direction = services.parse_record(rec())
        self.assertEqual((code, serial, direction), ("104", "DEV1", ""))
        self.assertTrue(timezone.is_aware(when))
        self.assertEqual(when, datetime(2026, 11, 25, 3, 31, 2, tzinfo=dt_tz.utc))

    def test_whitespace_is_stripped(self):
        code, serial, _, _ = services.parse_record(rec(code=" 7 ", serial=" S "))
        self.assertEqual((code, serial), ("7", "S"))

    def test_unusable_records_return_none(self):
        self.assertIsNone(services.parse_record(rec(code="")))
        self.assertIsNone(services.parse_record(rec(serial="")))
        self.assertIsNone(services.parse_record(rec(when="")))
        self.assertIsNone(services.parse_record(rec(when="not a date")))
        self.assertIsNone(services.parse_record(rec(when="2026-11-25")))
        self.assertIsNone(services.parse_record("a string"))
        self.assertIsNone(services.parse_record(None))
        self.assertIsNone(services.parse_record({}))


class DateWindowTests(SimpleTestCase):
    def test_windows_cover_range_with_one_day_overlap(self):
        wins = list(services.date_windows(date(2026, 11, 1), date(2026, 11, 20), 7))
        self.assertEqual(wins[0][0], date(2026, 11, 1))
        self.assertEqual(wins[-1][1], date(2026, 11, 20))
        for (_, prev_end), (next_start, _) in zip(wins, wins[1:]):
            self.assertEqual(next_start, prev_end)
        for start, end in wins:
            self.assertLessEqual(end - start, timedelta(days=6))

    def test_single_day(self):
        d = date(2026, 11, 25)
        self.assertEqual(list(services.date_windows(d, d, 7)), [(d, d)])

    def test_two_day_range_is_one_window(self):
        wins = list(services.date_windows(date(2026, 11, 24), date(2026, 11, 25), 7))
        self.assertEqual(wins, [(date(2026, 11, 24), date(2026, 11, 25))])

    def test_chunk_days_below_two_is_refused(self):
        with self.assertRaises(ValueError):
            list(services.date_windows(date(2026, 11, 1), date(2026, 11, 5), 1))

    def test_from_after_to_gives_nothing(self):
        self.assertEqual(
            list(services.date_windows(date(2026, 11, 5), date(2026, 11, 1), 7)), []
        )


class FetchLogsTests(SimpleTestCase):
    d1, d2 = date(2026, 11, 1), date(2026, 11, 2)

    def call(self):
        return services.fetch_logs(KEY, self.d1, self.d2, base_url="http://so.test")

    @mock.patch("app_biometric.services.request.urlopen")
    def test_list_is_success_and_url_is_built(self, urlopen):
        urlopen.return_value = fake_response('[{"EmployeeCode": "1"}]')
        self.assertEqual(self.call(), [{"EmployeeCode": "1"}])
        url = urlopen.call_args[0][0]
        self.assertIn("http://so.test/api/v2/WebAPI/GetDeviceLogs?", url)
        self.assertIn("FromDate=2026-11-01", url)
        self.assertIn("ToDate=2026-11-02", url)

    @mock.patch("app_biometric.services.request.urlopen")
    def test_bom_is_tolerated(self, urlopen):
        urlopen.return_value = fake_response("﻿[]")
        self.assertEqual(self.call(), [])

    @mock.patch("app_biometric.services.request.urlopen")
    def test_error_string_and_object_are_failures(self, urlopen):
        for body in ['"Invalid API key"', '{"Message":"An error has occurred."}', "null", "5"]:
            urlopen.return_value = fake_response(body)
            with self.assertRaises(services.SmartOfficeError, msg=body):
                self.call()

    @mock.patch("app_biometric.services.request.urlopen")
    def test_not_json_is_failure(self, urlopen):
        urlopen.return_value = fake_response("<html>oops</html>")
        with self.assertRaises(services.SmartOfficeError):
            self.call()

    @mock.patch("app_biometric.services.request.urlopen")
    def test_key_echoed_by_server_is_scrubbed(self, urlopen):
        urlopen.return_value = fake_response('"bad key ' + KEY + '"')
        with self.assertRaises(services.SmartOfficeError) as cm:
            self.call()
        self.assertNotIn(KEY, str(cm.exception))
        self.assertIn("***", str(cm.exception))

    @mock.patch("app_biometric.services.request.urlopen")
    def test_network_error_hides_key(self, urlopen):
        urlopen.side_effect = error.URLError(f"failed for {KEY}")
        with self.assertRaises(services.SmartOfficeError) as cm:
            self.call()
        self.assertNotIn(KEY, str(cm.exception))
        self.assertIsNone(cm.exception.__cause__)
        self.assertTrue(cm.exception.__suppress_context__)

    @mock.patch("app_biometric.services.request.urlopen")
    def test_http_error_hides_key_and_url(self, urlopen):
        urlopen.side_effect = error.HTTPError(
            f"http://so.test/?APIKey={KEY}", 500, "boom", {}, None
        )
        with self.assertRaises(services.SmartOfficeError) as cm:
            self.call()
        self.assertEqual(str(cm.exception), "HTTP 500 from Smart Office")
        self.assertTrue(cm.exception.__suppress_context__)


class IngestTests(TestCase):
    def setUp(self):
        self.org = make_org("Org A")

    def test_stores_punches_devices_identities_and_counts_skips(self):
        records = [
            rec("104", "2026-11-25 09:01:02", "DEV1"),
            rec("104", "2026-11-25 18:01:02", "DEV1"),
            rec("105", "2026-11-25 09:05:00", "DEV2"),
            rec("", "2026-11-25 09:05:00", "DEV2"),
            rec("9", "garbage", "DEV2"),
        ]
        stats = services.ingest_records(self.org, records)
        self.assertEqual(stats, {"fetched": 5, "skipped": 2, "new": 3})
        self.assertEqual(PunchLog.objects.filter(organization=self.org).count(), 3)
        self.assertEqual(BiometricDevice.objects.filter(organization=self.org).count(), 2)
        self.assertEqual(
            set(BiometricIdentity.objects.values_list("device_code", flat=True)),
            {"104", "105"},
        )
        self.assertFalse(BiometricIdentity.objects.exclude(employee=None).exists())

    def test_punch_time_is_stored_as_correct_instant(self):
        services.ingest_records(self.org, [rec(when="2026-11-25 09:01:02")])
        p = PunchLog.objects.get()
        self.assertEqual(p.punch_time, datetime(2026, 11, 25, 3, 31, 2, tzinfo=dt_tz.utc))

    def test_rerun_adds_nothing(self):
        records = [rec("104"), rec("105", "2026-11-25 10:00:00")]
        services.ingest_records(self.org, records)
        stats = services.ingest_records(self.org, records)
        self.assertEqual(stats["new"], 0)
        self.assertEqual(PunchLog.objects.count(), 2)
        self.assertEqual(BiometricDevice.objects.count(), 1)
        self.assertEqual(BiometricIdentity.objects.count(), 2)

    def test_duplicate_inside_one_batch_stored_once(self):
        stats = services.ingest_records(self.org, [rec(), rec()])
        self.assertEqual(stats["new"], 1)
        self.assertEqual(PunchLog.objects.count(), 1)

    def test_same_time_different_device_is_two_punches(self):
        services.ingest_records(self.org, [rec(serial="DEV1"), rec(serial="DEV2")])
        self.assertEqual(PunchLog.objects.count(), 2)

    def test_two_orgs_stay_separate(self):
        other = make_org("Org B")
        services.ingest_records(self.org, [rec()])
        services.ingest_records(other, [rec()])
        self.assertEqual(PunchLog.objects.filter(organization=self.org).count(), 1)
        self.assertEqual(PunchLog.objects.filter(organization=other).count(), 1)
        self.assertEqual(BiometricDevice.objects.count(), 2)
        self.assertEqual(BiometricIdentity.objects.count(), 2)

    def test_existing_link_and_project_are_not_overwritten(self):
        project = make_project(self.org, "CHK")
        profile = make_profile(self.org, "emp104")
        device = BiometricDevice.objects.create(
            organization=self.org, serial_number="DEV1", name="Gate", project=project
        )
        ident = BiometricIdentity.objects.create(
            organization=self.org, device_code="104", employee=profile
        )
        services.ingest_records(self.org, [rec("104", serial="DEV1")])
        device.refresh_from_db()
        ident.refresh_from_db()
        self.assertEqual(device.project, project)
        self.assertEqual(device.name, "Gate")
        self.assertEqual(ident.employee, profile)
        self.assertEqual(PunchLog.objects.get().device, device)


class SyncRangeTests(TestCase):
    def setUp(self):
        self.org = make_org("Org A")
        self.calls = []

    def fetcher(self, api_key, start, end):
        self.calls.append((api_key, start, end))
        return [rec()]

    def test_success_run_is_recorded(self):
        msgs = []
        run = services.sync_range(
            self.org,
            date(2026, 11, 1),
            date(2026, 11, 14),
            SyncRun.MODE_RANGE,
            KEY,
            chunk_days=7,
            fetcher=self.fetcher,
            progress=msgs.append,
        )
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(run.status, SyncRun.STATUS_SUCCESS)
        self.assertIsNotNone(run.finished_at)
        self.assertEqual(
            (run.api_calls, run.records_fetched, run.records_new, run.records_skipped),
            (3, 3, 1, 0),
        )
        self.assertEqual(len(msgs), 3)
        self.assertFalse(any(KEY in m for m in msgs))
        self.assertEqual(SyncRun.objects.count(), 1)

    def test_error_marks_run_failed_and_stops(self):
        def flaky(api_key, start, end):
            self.calls.append(start)
            if len(self.calls) == 2:
                raise services.SmartOfficeError("boom")
            return [rec()]

        with self.assertRaises(services.SmartOfficeError):
            services.sync_range(
                self.org, date(2026, 11, 1), date(2026, 11, 20),
                SyncRun.MODE_RANGE, KEY, fetcher=flaky,
            )
        run = SyncRun.objects.get()
        self.assertEqual(run.status, SyncRun.STATUS_FAILED)
        self.assertTrue(run.error_message.startswith("boom"))
        self.assertIn("re-run with --from", run.error_message)
        self.assertEqual(run.api_calls, 1)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(PunchLog.objects.count(), 1)

    def test_unexpected_error_is_recorded_without_details(self):
        def broken(api_key, start, end):
            raise ValueError("leaky " + KEY)

        with self.assertRaises(ValueError):
            services.sync_range(
                self.org, date(2026, 11, 1), date(2026, 11, 2),
                SyncRun.MODE_RANGE, KEY, fetcher=broken,
            )
        run = SyncRun.objects.get()
        self.assertEqual(run.status, SyncRun.STATUS_FAILED)
        self.assertEqual(run.error_message, "unexpected error: ValueError")
        self.assertNotIn(KEY, run.error_message)

    def test_recent_running_sync_blocks_a_new_one(self):
        SyncRun.objects.create(
            organization=self.org, mode=SyncRun.MODE_DAILY,
            from_date=date(2026, 11, 25), to_date=date(2026, 11, 26),
        )
        with self.assertRaises(services.SmartOfficeError):
            services.sync_range(
                self.org, date(2026, 11, 25), date(2026, 11, 26),
                SyncRun.MODE_DAILY, KEY, fetcher=self.fetcher,
            )
        self.assertEqual(SyncRun.objects.count(), 1)
        self.assertEqual(self.calls, [])

    def test_stale_running_sync_does_not_block(self):
        SyncRun.objects.create(
            organization=self.org, mode=SyncRun.MODE_DAILY,
            from_date=date(2026, 11, 25), to_date=date(2026, 11, 26),
            started_at=timezone.now() - timedelta(hours=5),
        )
        run = services.sync_range(
            self.org, date(2026, 11, 25), date(2026, 11, 26),
            SyncRun.MODE_DAILY, KEY, fetcher=self.fetcher,
        )
        self.assertEqual(run.status, SyncRun.STATUS_SUCCESS)

    def test_other_orgs_running_sync_does_not_block(self):
        other = make_org("Org B")
        SyncRun.objects.create(
            organization=other, mode=SyncRun.MODE_DAILY,
            from_date=date(2026, 11, 25), to_date=date(2026, 11, 26),
        )
        run = services.sync_range(
            self.org, date(2026, 11, 25), date(2026, 11, 26),
            SyncRun.MODE_DAILY, KEY, fetcher=self.fetcher,
        )
        self.assertEqual(run.status, SyncRun.STATUS_SUCCESS)

    def test_dry_run_writes_nothing(self):
        totals = services.dry_run_range(
            date(2026, 11, 1), date(2026, 11, 2), KEY, fetcher=self.fetcher
        )
        self.assertEqual(totals["fetched"], 1)
        self.assertEqual(totals["valid"], 1)
        self.assertEqual(totals["distinct_codes"], 1)
        self.assertEqual(PunchLog.objects.count(), 0)
        self.assertEqual(SyncRun.objects.count(), 0)
        self.assertEqual(BiometricDevice.objects.count(), 0)


@override_settings(SMARTOFFICE_API_KEY=KEY)
class CommandTests(TestCase):
    def setUp(self):
        self.org = make_org("Org A")

    def run_cmd(self, *args):
        out = StringIO()
        call_command("sync_smartoffice", *args, stdout=out)
        return out.getvalue()

    @mock.patch("app_biometric.services.fetch_logs", return_value=[rec()])
    def test_backfill_writes_and_prints_counts_only(self, fetch):
        out = self.run_cmd("--org-id", str(self.org.pk), "--from", "2026-11-24", "--to", "2026-11-26")
        self.assertIn("Done", out)
        self.assertIn("new 1", out)
        self.assertNotIn(KEY, out)
        self.assertNotIn("104", out)
        self.assertEqual(PunchLog.objects.count(), 1)
        self.assertEqual(SyncRun.objects.get().mode, SyncRun.MODE_RANGE)

    @mock.patch("app_biometric.services.fetch_logs", return_value=[rec()])
    def test_dry_run_writes_nothing(self, fetch):
        out = self.run_cmd("--org-id", str(self.org.pk), "--from", "2026-11-24", "--dry-run")
        self.assertIn("DRY RUN", out)
        self.assertNotIn(KEY, out)
        self.assertEqual(PunchLog.objects.count(), 0)
        self.assertEqual(SyncRun.objects.count(), 0)

    def test_default_is_yesterday_to_today(self):
        seen = []

        def fetch(api_key, start, end):
            seen.append((start, end))
            return []

        with mock.patch("app_biometric.services.fetch_logs", side_effect=fetch):
            self.run_cmd("--org-id", str(self.org.pk))
        today = timezone.localdate()
        self.assertEqual(seen, [(today - timedelta(days=1), today)])
        self.assertEqual(SyncRun.objects.get().mode, SyncRun.MODE_DAILY)

    @override_settings(SMARTOFFICE_API_KEY="")
    def test_missing_key_is_refused(self):
        with self.assertRaises(CommandError):
            self.run_cmd("--org-id", str(self.org.pk))

    def test_unknown_org_is_refused(self):
        with self.assertRaises(CommandError):
            self.run_cmd("--org-id", "999999")

    def test_bad_arguments_are_refused(self):
        org = str(self.org.pk)
        for args in [
            ["--from", "25-11-2026"],
            ["--from", "2026-11-26", "--to", "2026-11-01"],
            ["--from", "2026-11-01", "--chunk-days", "1"],
        ]:
            with self.assertRaises(CommandError, msg=str(args)):
                self.run_cmd("--org-id", org, *args)
        self.assertEqual(SyncRun.objects.count(), 0)

    @mock.patch(
        "app_biometric.services.fetch_logs",
        side_effect=services.SmartOfficeError("Smart Office returned an error: nope"),
    )
    def test_vendor_error_becomes_command_error_and_failed_run(self, fetch):
        with self.assertRaises(CommandError):
            self.run_cmd("--org-id", str(self.org.pk), "--from", "2026-11-24")
        self.assertEqual(SyncRun.objects.get().status, SyncRun.STATUS_FAILED)
        self.assertEqual(PunchLog.objects.count(), 0)


class ModelRuleTests(TestCase):
    def setUp(self):
        self.org = make_org("Org A")
        self.other = make_org("Org B")

    def test_device_project_must_be_same_org(self):
        project = make_project(self.other, "XYZ")
        device = BiometricDevice(organization=self.org, serial_number="D", project=project)
        with self.assertRaises(ValidationError):
            device.full_clean()
        device.project = make_project(self.org, "CHK")
        device.full_clean()

    def test_identity_employee_must_be_same_org(self):
        profile = make_profile(self.other, "outsider")
        ident = BiometricIdentity(organization=self.org, device_code="1", employee=profile)
        with self.assertRaises(ValidationError):
            ident.full_clean()

    def test_one_code_per_org_and_one_code_per_employee(self):
        profile = make_profile(self.org, "emp1")
        BiometricIdentity.objects.create(organization=self.org, device_code="1", employee=profile)
        with self.assertRaises(IntegrityError), transaction.atomic():
            BiometricIdentity.objects.create(organization=self.org, device_code="1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            BiometricIdentity.objects.create(organization=self.org, device_code="2", employee=profile)
        BiometricIdentity.objects.create(organization=self.org, device_code="3")
        BiometricIdentity.objects.create(organization=self.org, device_code="4")
        BiometricIdentity.objects.create(organization=self.other, device_code="1")

    def test_duplicate_punch_is_refused_by_database(self):
        dev = BiometricDevice.objects.create(organization=self.org, serial_number="D")
        when = timezone.now()
        PunchLog.objects.create(organization=self.org, device=dev, employee_code="1", punch_time=when)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PunchLog.objects.create(organization=self.org, device=dev, employee_code="1", punch_time=when)

    def test_device_with_punches_cannot_be_deleted(self):
        dev = BiometricDevice.objects.create(organization=self.org, serial_number="D")
        PunchLog.objects.create(organization=self.org, device=dev, employee_code="1", punch_time=timezone.now())
        with self.assertRaises(ProtectedError):
            dev.delete()

    def test_unlinking_employee_keeps_the_identity_and_punches(self):
        profile = make_profile(self.org, "emp1")
        ident = BiometricIdentity.objects.create(organization=self.org, device_code="1", employee=profile)
        profile.delete()
        ident.refresh_from_db()
        self.assertIsNone(ident.employee)


class AdminTests(TestCase):
    """Admin pages load for a superuser and punches cannot be added by hand."""

    def setUp(self):
        self.org = make_org("Org A")
        self.admin_user = get_user_model().objects.create_superuser(
            username="root@example.com", email="root@example.com", password="Test-pass-12345"
        )
        self.client.force_login(self.admin_user)
        services.ingest_records(self.org, [rec()])

    def test_changelists_load(self):
        for name in ["biometricdevice", "biometricidentity", "punchlog", "syncrun"]:
            url = reverse(f"admin:app_biometric_{name}_changelist")
            self.assertEqual(self.client.get(url).status_code, 200, msg=name)

    def test_punch_and_syncrun_cannot_be_added_or_changed(self):
        self.assertEqual(self.client.get(reverse("admin:app_biometric_punchlog_add")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:app_biometric_syncrun_add")).status_code, 403)
        punch = PunchLog.objects.get()
        url = reverse("admin:app_biometric_punchlog_delete", args=[punch.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
