import http.client
import io
from datetime import date
from unittest import mock
from urllib import error

from django.test import SimpleTestCase

from app_biometric import services


class SleepPatched(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch("app_biometric.services.time.sleep")
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)


def flaky(failures, exc_factory):
    calls = {"n": 0}

    def fetcher(api_key, start, end):
        calls["n"] += 1
        if calls["n"] <= failures:
            raise exc_factory()
        return ["ok"]

    return fetcher, calls


def transient():
    return services.SmartOfficeTransientError("blip")


class CallWithRetryTests(SleepPatched):
    def run_it(self, fetcher, retries, delay=2.0):
        return services.call_with_retry(
            fetcher, "k", date(2024, 4, 1), date(2024, 4, 7), retries, delay
        )

    def test_retries_then_succeeds(self):
        fetcher, calls = flaky(2, transient)
        self.assertEqual(self.run_it(fetcher, 4), ["ok"])
        self.assertEqual(calls["n"], 3)
        self.assertEqual(self.sleep.call_count, 2)

    def test_backoff_doubles(self):
        fetcher, _ = flaky(3, transient)
        self.run_it(fetcher, 4)
        waits = [c.args[0] for c in self.sleep.call_args_list]
        self.assertTrue(2 <= waits[0] <= 2.5)
        self.assertTrue(4 <= waits[1] <= 5)
        self.assertTrue(8 <= waits[2] <= 10)

    def test_gives_up_after_limit(self):
        fetcher, calls = flaky(10, transient)
        with self.assertRaises(services.SmartOfficeTransientError):
            self.run_it(fetcher, 2)
        self.assertEqual(calls["n"], 3)
        self.assertEqual(self.sleep.call_count, 2)

    def test_permanent_error_not_retried(self):
        fetcher, calls = flaky(10, lambda: services.SmartOfficeError("bad key"))
        with self.assertRaises(services.SmartOfficeError):
            self.run_it(fetcher, 4)
        self.assertEqual(calls["n"], 1)
        self.sleep.assert_not_called()

    def test_zero_retries_means_no_retry(self):
        fetcher, calls = flaky(1, transient)
        with self.assertRaises(services.SmartOfficeTransientError):
            self.run_it(fetcher, 0)
        self.assertEqual(calls["n"], 1)


class FetchLogsClassificationTests(SimpleTestCase):
    def call(self, side_effect=None, body=None):
        with mock.patch("app_biometric.services.request.urlopen") as urlopen:
            if side_effect is not None:
                urlopen.side_effect = side_effect
            else:
                resp = mock.MagicMock()
                resp.__enter__.return_value = resp
                resp.read.return_value = body
                urlopen.return_value = resp
            return services.fetch_logs(
                "secretkey",
                date(2024, 4, 1),
                date(2024, 4, 7),
                base_url="http://example.invalid",
            )

    def http_error(self, code):
        return error.HTTPError("http://x", code, "msg", {}, io.BytesIO(b""))

    def test_5xx_and_429_are_transient(self):
        for code in (500, 503, 429):
            with self.assertRaises(services.SmartOfficeTransientError):
                self.call(side_effect=self.http_error(code))

    def test_other_4xx_is_permanent(self):
        for code in (400, 401, 404):
            with self.assertRaises(services.SmartOfficeError) as ctx:
                self.call(side_effect=self.http_error(code))
            self.assertNotIsInstance(
                ctx.exception, services.SmartOfficeTransientError
            )

    def test_network_problems_are_transient(self):
        for exc in (
            error.URLError("down"),
            TimeoutError("slow"),
            http.client.IncompleteRead(b""),
        ):
            with self.assertRaises(services.SmartOfficeTransientError):
                self.call(side_effect=exc)

    def test_non_json_is_transient(self):
        with self.assertRaises(services.SmartOfficeTransientError):
            self.call(body=b"<html>oops</html>")

    def test_vendor_error_string_is_permanent(self):
        with self.assertRaises(services.SmartOfficeError) as ctx:
            self.call(body=b'"Invalid API key"')
        self.assertNotIsInstance(
            ctx.exception, services.SmartOfficeTransientError
        )

    def test_list_is_success(self):
        self.assertEqual(self.call(body=b"[]"), [])


class DryRunTests(SleepPatched):
    def test_pause_between_windows_only(self):
        fetcher = lambda api_key, start, end: []
        services.dry_run_range(
            date(2024, 4, 1), date(2024, 4, 20), "k", fetcher=fetcher, pause=1.5
        )
        self.assertEqual(self.sleep.call_args_list, [mock.call(1.5)] * 3)

    def test_no_pause_by_default(self):
        fetcher = lambda api_key, start, end: []
        services.dry_run_range(
            date(2024, 4, 1), date(2024, 4, 20), "k", fetcher=fetcher
        )
        self.sleep.assert_not_called()

    def test_retry_inside_dry_run(self):
        fetcher, calls = flaky(1, transient)
        totals = services.dry_run_range(
            date(2024, 4, 1),
            date(2024, 4, 5),
            "k",
            fetcher=lambda a, s, e: fetcher(a, s, e) and [],
            retries=2,
        )
        self.assertEqual(totals["calls"], 1)
        self.assertEqual(calls["n"], 2)

    def test_no_retry_by_default(self):
        fetcher, _ = flaky(1, transient)
        with self.assertRaises(services.SmartOfficeTransientError):
            services.dry_run_range(
                date(2024, 4, 1), date(2024, 4, 5), "k", fetcher=fetcher
            )
