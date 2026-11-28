"""Smart Office client and punch ingestion. No Django views; used by the command."""
import http.client
import json
import random
import time
from datetime import datetime, timedelta
from urllib import error, parse, request

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import BiometricDevice, BiometricIdentity, PunchLog, SyncRun

API_PATH = "/api/v2/WebAPI/GetDeviceLogs"
LOG_FORMAT = "%Y-%m-%d %H:%M:%S"
STALE_RUN_HOURS = 3


class SmartOfficeError(Exception):
    """Any failure talking to Smart Office. Messages never contain the API key."""

    retryable = False


class SmartOfficeTransientError(SmartOfficeError):
    """A failure worth retrying: network trouble, HTTP 5xx or 429."""

    retryable = True


def _scrub(text, api_key):
    text = str(text)
    if api_key:
        text = text.replace(api_key, "***")
    return text[:200]


def fetch_logs(api_key, from_date, to_date, base_url=None, timeout=90):
    """Return the JSON list of punches for the date range (date-only filtering).

    Smart Office reports errors as HTTP 200 with a JSON string or object, so
    only a JSON list counts as success.
    """
    base = (base_url or settings.SMARTOFFICE_BASE_URL).rstrip("/")
    query = parse.urlencode(
        {
            "APIKey": api_key,
            "FromDate": from_date.isoformat(),
            "ToDate": to_date.isoformat(),
        }
    )
    url = f"{base}{API_PATH}?{query}"
    try:
        with request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8-sig")
    except error.HTTPError as exc:
        cls = (
            SmartOfficeTransientError
            if exc.code == 429 or exc.code >= 500
            else SmartOfficeError
        )
        raise cls(f"HTTP {exc.code} from Smart Office") from None
    except (
        error.URLError,
        TimeoutError,
        OSError,
        http.client.HTTPException,
    ) as exc:
        reason = getattr(exc, "reason", exc)
        raise SmartOfficeTransientError(
            "could not reach Smart Office: " + _scrub(reason, api_key)
        ) from None
    try:
        data = json.loads(body)
    except ValueError:
        raise SmartOfficeTransientError("response was not JSON") from None
    if not isinstance(data, list):
        shown = data if isinstance(data, str) else json.dumps(data)
        raise SmartOfficeError(
            "Smart Office returned an error: " + _scrub(shown, api_key)
        )
    return data


def parse_record(rec):
    """Return (code, serial, aware_punch_time, direction) or None if unusable."""
    if not isinstance(rec, dict):
        return None
    code = str(rec.get("EmployeeCode") or "").strip()
    serial = str(rec.get("SerialNumber") or "").strip()
    raw_time = str(rec.get("LogDate") or "").strip()
    if not (code and serial and raw_time):
        return None
    try:
        naive = datetime.strptime(raw_time, LOG_FORMAT)
    except ValueError:
        return None
    punch_time = timezone.make_aware(naive)
    direction = str(rec.get("PunchDirection") or "").strip()[:16]
    return code[:64], serial[:64], punch_time, direction


def date_windows(from_date, to_date, chunk_days=7):
    """Yield (start, end) date windows covering the range.

    Each window starts on the previous window's end date (one day of overlap),
    so a day is never lost even if the API treats ToDate as exclusive.
    Duplicates are harmless because PunchLog is unique per device+code+time.
    """
    if chunk_days < 2:
        raise ValueError("chunk_days must be at least 2")
    start = from_date
    while start <= to_date:
        end = min(start + timedelta(days=chunk_days - 1), to_date)
        yield start, end
        if end >= to_date:
            break
        start = end


def ingest_records(organization, records):
    """Store a batch of API records. Returns counts only."""
    parsed = []
    skipped = 0
    for rec in records:
        item = parse_record(rec)
        if item is None:
            skipped += 1
        else:
            parsed.append(item)

    with transaction.atomic():
        serials = {p[1] for p in parsed}
        devices = {
            d.serial_number: d
            for d in BiometricDevice.objects.filter(
                organization=organization, serial_number__in=serials
            )
        }
        for serial in serials - devices.keys():
            devices[serial] = BiometricDevice.objects.create(
                organization=organization, serial_number=serial, name=serial
            )

        codes = {p[0] for p in parsed}
        known = set(
            BiometricIdentity.objects.filter(
                organization=organization, device_code__in=codes
            ).values_list("device_code", flat=True)
        )
        BiometricIdentity.objects.bulk_create(
            [
                BiometricIdentity(organization=organization, device_code=c)
                for c in codes - known
            ],
            ignore_conflicts=True,
        )

        before = PunchLog.objects.filter(organization=organization).count()
        PunchLog.objects.bulk_create(
            [
                PunchLog(
                    organization=organization,
                    device=devices[serial],
                    employee_code=code,
                    punch_time=punch_time,
                    direction=direction,
                )
                for code, serial, punch_time, direction in parsed
            ],
            batch_size=1000,
            ignore_conflicts=True,
        )
        after = PunchLog.objects.filter(organization=organization).count()

    return {"fetched": len(records), "skipped": skipped, "new": after - before}


def call_with_retry(
    fetcher, api_key, start, end, retries=0, delay=2.0, progress=None
):
    """Call fetcher; retry transient errors with doubling waits plus jitter."""
    attempt = 0
    while True:
        try:
            return fetcher(api_key, start, end)
        except SmartOfficeError as exc:
            if not getattr(exc, "retryable", False) or attempt >= retries:
                raise
            wait = delay * (2**attempt)
            wait += random.uniform(0, wait * 0.25)
            attempt += 1
            if progress:
                progress(
                    f"{start} to {end}: {exc}; retry {attempt} of {retries} "
                    f"in {wait:.0f}s"
                )
            time.sleep(wait)


def _fail(run, message):
    run.status = SyncRun.STATUS_FAILED
    run.error_message = message[:300]
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "error_message", "finished_at"])


def sync_range(
    organization,
    from_date,
    to_date,
    mode,
    api_key,
    chunk_days=7,
    fetcher=None,
    progress=None,
    retries=0,
    retry_delay=2.0,
    pause=0,
):
    """Pull the range from Smart Office and store it. Re-runnable at any time."""
    fetcher = fetcher or fetch_logs
    progress = progress or (lambda msg: None)

    cutoff = timezone.now() - timedelta(hours=STALE_RUN_HOURS)
    if SyncRun.objects.filter(
        organization=organization,
        status=SyncRun.STATUS_RUNNING,
        started_at__gte=cutoff,
    ).exists():
        raise SmartOfficeError(
            "another sync for this organization looks like it is still running"
        )

    run = SyncRun.objects.create(
        organization=organization, mode=mode, from_date=from_date, to_date=to_date
    )
    window = None
    try:
        for start, end in date_windows(from_date, to_date, chunk_days):
            if window is not None and pause:
                time.sleep(pause)
            window = (start, end)
            data = call_with_retry(
                fetcher, api_key, start, end, retries, retry_delay, progress
            )
            run.api_calls += 1
            stats = ingest_records(organization, data)
            run.records_fetched += stats["fetched"]
            run.records_new += stats["new"]
            run.records_skipped += stats["skipped"]
            run.save(
                update_fields=[
                    "api_calls",
                    "records_fetched",
                    "records_new",
                    "records_skipped",
                ]
            )
            progress(
                f"{start} to {end}: fetched {stats['fetched']}, "
                f"new {stats['new']}, skipped {stats['skipped']}"
            )
    except SmartOfficeError as exc:
        where = (
            f" (stopped at {window[0]} to {window[1]}; re-run with --from {window[0]})"
            if window
            else ""
        )
        _fail(run, str(exc) + where)
        raise
    except Exception as exc:
        _fail(run, "unexpected error: " + type(exc).__name__)
        raise
    run.status = SyncRun.STATUS_SUCCESS
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "finished_at"])
    return run


def dry_run_range(
    from_date,
    to_date,
    api_key,
    chunk_days=7,
    fetcher=None,
    progress=None,
    retries=0,
    retry_delay=2.0,
    pause=0,
):
    """Fetch and count only. Writes nothing to the database."""
    fetcher = fetcher or fetch_logs
    progress = progress or (lambda msg: None)
    totals = {"calls": 0, "fetched": 0, "valid": 0, "skipped": 0}
    codes, serials = set(), set()
    first = True
    for start, end in date_windows(from_date, to_date, chunk_days):
        if not first and pause:
            time.sleep(pause)
        first = False
        data = call_with_retry(
            fetcher, api_key, start, end, retries, retry_delay, progress
        )
        totals["calls"] += 1
        valid = 0
        for rec in data:
            item = parse_record(rec)
            if item is None:
                totals["skipped"] += 1
            else:
                valid += 1
                codes.add(item[0])
                serials.add(item[1])
        totals["fetched"] += len(data)
        totals["valid"] += valid
        progress(f"{start} to {end}: fetched {len(data)}, valid {valid}")
    totals["distinct_codes"] = len(codes)
    totals["distinct_devices"] = len(serials)
    return totals
