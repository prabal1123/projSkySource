"""
audit_biometric_link  (READ-ONLY, prints COUNTS ONLY)

Answers four questions before anything is built or imported:
  1. What does Smart Office hold?         (punches from the API, optional)
  2. What is in the employee export file? (CSV or XLSX, headings and counts)
  3. What does our own database hold?     (employees, emails, phone fingerprints)
  4. How many device codes can be linked to our employees, and how?

Safety
  * Never writes to the database. Only SELECTs.
  * Never prints names, emails, phone numbers, employee codes or the API key.
  * Phone matching reuses appEmp.blind_index.phone_index, so no phone number
    is ever decrypted. Employee rows are read with values_list on plain
    columns only.
  * --review-file writes ONLY employee codes and a reason, nothing else.

Install:  copy this file to appEmp/management/commands/audit_biometric_link.py

Examples
  python manage.py audit_biometric_link --csv ~/Downloads/export.xlsx
  python manage.py audit_biometric_link --csv ~/Downloads/export.xlsx --api --from 2026-10-28
  python manage.py audit_biometric_link --csv export.csv --api --org-id 1 --review-file /tmp/review.csv

The API key is read from SMARTOFFICE_API_KEY, or typed hidden when prompted.
"""
import csv
import getpass
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError

from appEmp.blind_index import BlindIndexError, phone_index
from appEmp.models import empProfile

DEFAULT_BASE_URL = "http://47.247.38.66:82/api/v2/WebAPI/GetDeviceLogs"
CHUNK_DAYS = 7          # weekly calls: about 2 s each, a month in one call took 23 s
PAUSE_SECONDS = 1.0     # be gentle with the vendor's server


# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------
def _cell_to_str(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # phone numbers stored as numbers in Excel
    return str(value).strip()


def _read_table(path):
    """Return (headers, rows) from a .xlsx or delimited text file."""
    if not os.path.exists(path):
        raise CommandError("File not found: %s" % path)

    if path.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        try:
            first = next(it)
        except StopIteration:
            raise CommandError("The spreadsheet is empty.")
        headers = [_cell_to_str(c) for c in first]
        rows = []
        for raw in it:
            if raw is None or all(c is None or _cell_to_str(c) == "" for c in raw):
                continue
            rows.append({h: _cell_to_str(c) for h, c in zip(headers, raw)})
        wb.close()
        return headers, rows

    with open(path, newline="", encoding="utf-8-sig") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(fh, dialect=dialect)
        headers = [(h or "").strip() for h in (reader.fieldnames or [])]
        rows = []
        for raw in reader:
            row = {(k or "").strip(): _cell_to_str(v) for k, v in raw.items()}
            if any(row.values()):
                rows.append(row)
        return headers, rows


def _col(headers, *names):
    """Find a column by name, ignoring case and spaces."""
    wanted = {n.lower().replace(" ", "") for n in names}
    for h in headers:
        if h.lower().replace(" ", "") in wanted:
            return h
    return None


def _norm_email(value):
    value = (value or "").strip().lower()
    return value if "@" in value else ""


def _chunks(d_from, d_to, days):
    cur = d_from
    while cur <= d_to:
        end = min(cur + timedelta(days=days - 1), d_to)
        yield cur, end
        cur = end + timedelta(days=1)


def _fetch(base_url, key, d_from, d_to):
    query = urllib.parse.urlencode(
        {"APIKey": key, "FromDate": d_from.isoformat(), "ToDate": d_to.isoformat()}
    )
    try:
        with urllib.request.urlopen("%s?%s" % (base_url, query), timeout=120) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CommandError("Could not reach Smart Office (%s)." % type(exc).__name__)
    try:
        data = json.loads(body)
    except ValueError:
        raise CommandError("Smart Office returned something that is not JSON.")
    # Errors come back as HTTP 200 with a string or an object. Only a list is success.
    if not isinstance(data, list):
        hint = data if isinstance(data, str) else "an object"
        raise CommandError("API did not return a list: %s" % str(hint)[:60])
    return data


# ----------------------------------------------------------------------
# Command
# ----------------------------------------------------------------------
class Command(BaseCommand):
    help = "Read-only audit of Smart Office data vs our employees. Counts only."

    def add_arguments(self, parser):
        parser.add_argument("--csv", dest="table_path",
                            help="Employee export from Smart Office (.csv or .xlsx).")
        parser.add_argument("--api", action="store_true",
                            help="Also pull punches from the API for the date range.")
        parser.add_argument("--from", dest="date_from",
                            help="API start date YYYY-MM-DD (default: 28 days ago).")
        parser.add_argument("--to", dest="date_to",
                            help="API end date YYYY-MM-DD (default: today).")
        parser.add_argument("--org-id", type=int,
                            help="Only match against employees of this organization id.")
        parser.add_argument("--review-file",
                            help="Write codes (and reason only) that need manual review.")
        parser.add_argument("--base-url",
                            default=os.environ.get("SMARTOFFICE_BASE_URL", DEFAULT_BASE_URL))

    def out(self, text=""):
        self.stdout.write(text)

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        if not opts["table_path"] and not opts["api"]:
            self.out("Nothing to compare. Use --csv and/or --api. Showing database counts only.")
        self.out("=" * 64)
        self.out("READ-ONLY AUDIT. Counts only; nothing is written or printed in full.")
        self.out("=" * 64)

        punch_stats = self.part_api(opts) if opts["api"] else None
        table = self.part_file(opts["table_path"]) if opts["table_path"] else None
        db = self.part_database(opts["org_id"])
        if table:
            self.part_link(table, db, punch_stats, opts)

    # ------------------------------------------------------------------
    # 1. Smart Office punches
    # ------------------------------------------------------------------
    def part_api(self, opts):
        self.out("\n[1] SMART OFFICE PUNCHES (API)")
        key = os.environ.get("SMARTOFFICE_API_KEY") or getpass.getpass("API key (hidden): ")
        if not key:
            raise CommandError("No API key given.")

        today = date.today()
        try:
            d_to = datetime.strptime(opts["date_to"], "%Y-%m-%d").date() if opts["date_to"] else today
            d_from = (datetime.strptime(opts["date_from"], "%Y-%m-%d").date()
                      if opts["date_from"] else d_to - timedelta(days=28))
        except ValueError:
            raise CommandError("Dates must look like 2026-11-25.")
        if d_from > d_to:
            raise CommandError("--from must not be after --to.")

        codes, serials, days = Counter(), Counter(), set()
        first_seen = last_seen = None
        calls = 0
        for a, b in _chunks(d_from, d_to, CHUNK_DAYS):
            rows = _fetch(opts["base_url"], key, a, b)
            calls += 1
            for r in rows:
                code = _cell_to_str(r.get("EmployeeCode"))
                codes[code] += 1
                serials[_cell_to_str(r.get("SerialNumber"))] += 1
                stamp = _cell_to_str(r.get("LogDate"))
                if stamp:
                    days.add(stamp[:10])
                    first_seen = stamp if first_seen is None or stamp < first_seen else first_seen
                    last_seen = stamp if last_seen is None or stamp > last_seen else last_seen
            time.sleep(PAUSE_SECONDS)

        total = sum(codes.values())
        self.out("  range requested     : %s to %s (%d calls)" % (d_from, d_to, calls))
        self.out("  punches returned    : %d" % total)
        self.out("  distinct codes      : %d" % len(codes))
        self.out("  days with punches   : %d" % len(days))
        self.out("  first / last punch  : %s / %s" % (first_seen or "-", last_seen or "-"))
        self.out("  punches per device  :")
        for serial, n in serials.most_common():
            self.out("      %-20s %d" % (serial or "(blank)", n))
        if "" in codes:
            self.out("  WARNING: %d punches have a blank EmployeeCode" % codes[""])
        return {"codes": codes, "total": total}

    # ------------------------------------------------------------------
    # 2. Employee export file
    # ------------------------------------------------------------------
    def part_file(self, path):
        self.out("\n[2] EMPLOYEE EXPORT FILE")
        headers, rows = _read_table(path)
        c_code = _col(headers, "EmployeeCode", "EmpCode", "Employee Code")
        c_mail = _col(headers, "Email", "OfficialEmail")
        c_pmail = _col(headers, "PersonaleMailID", "PersonalMailID", "PersonalEmail")
        c_phone = _col(headers, "ContactNo", "Mobile", "Phone", "MobileNo")
        c_name = _col(headers, "EmployeeName", "Name", "StaffName")

        self.out("  columns found       : %d" % len(headers))
        self.out("  rows                : %d" % len(rows))
        for label, col in (("code", c_code), ("email", c_mail), ("personal email", c_pmail),
                           ("phone", c_phone), ("name", c_name)):
            self.out("  %-20s: %s" % (label + " column", "present" if col else "MISSING"))
        if not c_code:
            raise CommandError("The file has no EmployeeCode column, so nothing can be linked.")

        codes = [r.get(c_code, "") for r in rows]
        non_empty = [c for c in codes if c]
        dup_codes = sum(1 for _, n in Counter(non_empty).items() if n > 1)
        self.out("  rows with a code    : %d" % len(non_empty))
        self.out("  codes used twice    : %d" % dup_codes)
        if c_mail:
            mails = [_norm_email(r.get(c_mail)) for r in rows]
            self.out("  rows with email     : %d" % sum(1 for m in mails if m))
            self.out("  emails used twice   : %d" % sum(1 for _, n in Counter(m for m in mails if m).items() if n > 1))
        if c_pmail:
            self.out("  rows w/ personal em.: %d" % sum(1 for r in rows if _norm_email(r.get(c_pmail))))
        if c_phone:
            digits_ok = sum(1 for r in rows if sum(ch.isdigit() for ch in r.get(c_phone, "")) >= 10)
            self.out("  rows with usable ph.: %d" % digits_ok)
        return {"rows": rows, "c_code": c_code, "c_mail": c_mail,
                "c_pmail": c_pmail, "c_phone": c_phone}

    # ------------------------------------------------------------------
    # 3. Our database
    # ------------------------------------------------------------------
    def part_database(self, org_id):
        self.out("\n[3] OUR DATABASE (employees)")
        qs = empProfile.objects.all()
        if org_id:
            qs = qs.filter(organization_id=org_id)
        # Plain columns only: no encrypted field is loaded, so nothing is decrypted.
        rows = list(qs.values_list("pk", "user__email", "user__username",
                                   "phone_bidx", "is_active", "organization_id",
                                   "organization__name"))
        orgs = Counter((r[5], r[6]) for r in rows)
        self.out("  employees in scope  : %d  (active: %d)" % (len(rows), sum(1 for r in rows if r[4])))
        self.out("  organizations       :")
        for (oid, oname), n in sorted(orgs.items(), key=lambda kv: -kv[1]):
            self.out("      id=%-4s %-30s %d" % (oid, (oname or "")[:30], n))
        if not org_id and len(orgs) > 1:
            self.out("  NOTE: several organizations are in scope. Re-run with --org-id to avoid cross-org matches.")

        email_map, phone_map = defaultdict(set), defaultdict(set)
        for pk, email, username, bidx, _active, _oid, _oname in rows:
            for candidate in (email, username):
                e = _norm_email(candidate)
                if e:
                    email_map[e].add(pk)
            if bidx:
                phone_map[bidx].add(pk)
        self.out("  with an email       : %d" % len({pk for s in email_map.values() for pk in s}))
        self.out("  with a phone index  : %d" % len({pk for s in phone_map.values() for pk in s}))
        return {"email_map": email_map, "phone_map": phone_map, "total": len(rows)}

    # ------------------------------------------------------------------
    # 4. Link coverage
    # ------------------------------------------------------------------
    def part_link(self, table, db, punch_stats, opts):
        self.out("\n[4] HOW MANY DEVICE CODES CAN BE LINKED")
        email_map, phone_map = db["email_map"], db["phone_map"]
        c_code, c_mail, c_pmail, c_phone = (table["c_code"], table["c_mail"],
                                            table["c_pmail"], table["c_phone"])
        counts = Counter()
        linked = {}                 # code -> profile pk
        review = []                 # (code, reason)
        phone_error_reported = False

        for row in table["rows"]:
            code = row.get(c_code, "")
            if not code:
                counts["no code in file"] += 1
                continue

            # --- email, then personal email ---
            decided = False
            for col, label in ((c_mail, "email"), (c_pmail, "personal email")):
                email = _norm_email(row.get(col)) if col else ""
                ids = email_map.get(email) if email else None
                if not ids:
                    continue
                if len(ids) == 1:
                    counts["matched by " + label] += 1
                    linked[code] = next(iter(ids))
                else:
                    counts["ambiguous (" + label + " shared)"] += 1
                    review.append((code, "ambiguous " + label))
                decided = True
                break
            if decided:
                continue

            # --- phone fingerprint ---
            if c_phone and row.get(c_phone):
                try:
                    bidx = phone_index(row.get(c_phone))
                except (BlindIndexError, ImproperlyConfigured) as exc:
                    bidx = None
                    if isinstance(exc, ImproperlyConfigured) and not phone_error_reported:
                        self.out("  NOTE: BLIND_INDEX_KEY is not set here, so phone matching is skipped.")
                        phone_error_reported = True
                ids = phone_map.get(bidx) if bidx else None
                if ids:
                    if len(ids) == 1:
                        counts["matched by phone"] += 1
                        linked[code] = next(iter(ids))
                    else:
                        counts["ambiguous (phone shared)"] += 1
                        review.append((code, "ambiguous phone"))
                    continue

            counts["unmatched"] += 1
            review.append((code, "unmatched"))

        for label in ("matched by email", "matched by personal email", "matched by phone",
                      "ambiguous (email shared)", "ambiguous (personal email shared)",
                      "ambiguous (phone shared)", "unmatched", "no code in file"):
            if counts.get(label):
                self.out("  %-34s: %d" % (label, counts[label]))
        self.out("  %-34s: %d" % ("TOTAL LINKED", len(linked)))

        claimed = Counter(linked.values())
        clashes = sum(1 for _, n in claimed.items() if n > 1)
        if clashes:
            self.out("  WARNING: %d employees are claimed by more than one device code." % clashes)
        self.out("  employees in scope without a code: %d" % max(db["total"] - len(claimed), 0))

        if punch_stats:
            pcodes = punch_stats["codes"]
            file_codes = {r.get(c_code, "") for r in table["rows"] if r.get(c_code, "")}
            in_file = {c for c in pcodes if c in file_codes}
            linked_punches = sum(n for c, n in pcodes.items() if c in linked)
            self.out("\n  PUNCH COVERAGE (range pulled from the API)")
            self.out("  punch codes found in the file    : %d of %d" % (len(in_file), len(pcodes)))
            self.out("  file codes with no punches       : %d" % len(file_codes - set(pcodes)))
            if punch_stats["total"]:
                self.out("  punches that belong to a linkable employee: %d of %d (%.1f%%)" % (
                    linked_punches, punch_stats["total"],
                    100.0 * linked_punches / punch_stats["total"]))

        if opts["review_file"]:
            with open(opts["review_file"], "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["EmployeeCode", "reason"])
                w.writerows(review)
            self.out("\n  review file written (%d codes, no personal data): %s" % (
                len(review), opts["review_file"]))
        self.out("\nDone. Nothing was written to the database.")