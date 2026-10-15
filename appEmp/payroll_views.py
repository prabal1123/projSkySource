"""
Payroll screens (Payroll Phase 3).

  payroll/                                  -> redirects to the month to work on
  payroll/<year>/<month>/                   -> roster for the month
  payroll/<year>/<month>/<employee uuid>/   -> one employee's breakdown

Both month pages accept POST actions (calculate / lock / unlock). On the roster
they apply to everyone currently in view (respecting the project filter); on
the employee page they apply to that employee only.

Rules enforced here:
  * Only users with the manage_salary permission (or superusers) get in.
  * Everything is scoped to request.current_org.
  * A month can only be locked after it has ended.
  * Locked rows show the saved snapshot, never a fresh calculation.
"""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from app_projects.filters import apply_project_filter, project_filter_context

from .models import PayrollRecord, empProfile
from .payslip_pdf import build_payroll_summary_pdf, build_payslip_pdf
from .payroll_service import (
    calculate_payroll_for_employees,
    earned_split,
    get_month_range,
    save_payroll_record,
)

ZERO = Decimal("0")
ACTIONS = {"calculate", "lock", "unlock"}


def _can_manage_payroll(user):
    return user.is_superuser or user.has_perm("appEmp.manage_salary")


def _validate_month(year, month):
    if not (2000 <= year <= 2100 and 1 <= month <= 12):
        raise Http404("Invalid payroll month.")


def _previous_month(today):
    return (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)


def _shift_month(year, month, delta):
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _guard(request):
    """Return a redirect response if the user may not use payroll, else None."""
    if not _can_manage_payroll(request.user):
        messages.error(request, "You don't have permission to manage payroll.")
        return redirect("dashboard")
    if getattr(request, "current_org", None) is None:
        messages.error(request, "No organization is selected.")
        return redirect("dashboard")
    return None


def _month_employees(request, year, month, project_selected):
    """
    Employees who may need payroll for this month: active ones, anyone who left
    during/after the month, and anyone who already has a record for it.
    """
    start, end = get_month_range(year, month)
    qs = (
        empProfile.objects.filter(organization=request.current_org)
        .filter(
            Q(is_active=True)
            | Q(payroll_records__year=year, payroll_records__month=month)
            | Q(
                exit_requests__status="COMPLETED",
                exit_requests__final_last_working_date__gte=start,
            )
        )
        .exclude(date_hired__gt=end)
        .distinct()
        .select_related("user", "designation", "project")
        .order_by("user__first_name", "user__last_name", "pk")
    )
    return apply_project_filter(qs, project_selected, path="project")


def _build_rows(employees, year, month, as_of=None):
    """
    One row per employee: the live calculation, the saved record (if any) and
    the figures to display. Locked rows display the snapshot.
    """
    employees = list(employees)
    results = calculate_payroll_for_employees(employees, year, month, as_of=as_of)
    records = {
        r.employee_id: r
        for r in PayrollRecord.objects.filter(
            employee__in=employees, year=year, month=month
        )
    }

    rows = []
    for emp, result in zip(employees, results):
        record = records.get(emp.pk)

        # Someone who was never employed in this month is not part of its payroll.
        if (
            not result.skipped
            and result.not_employed_days == result.days_in_period
            and record is None
        ):
            continue

        locked = bool(record and record.is_locked)
        if locked:
            state = "locked"
        elif result.skipped:
            state = "skipped"
        elif record is not None:
            state = "draft"
        else:
            state = "new"

        row = {
            "employee": emp,
            "result": result,
            "record": record,
            "state": state,
            "locked": locked,
            "stale": False,
            "figures": None,
        }

        if locked:
            source = record
        elif not result.skipped:
            source = result
        else:
            source = None

        if source is not None:
            row["figures"] = {
                "present_days": source.present_days,
                "leave_days": source.paid_leave_days,  # unpaid leave is in lop_days
                "lop_days": source.lop_days,
                "payable_days": source.payable_days,
                "gross_earned": source.gross_earned,
                "total_deductions": source.total_deductions,
                "net_pay": source.net_pay,
            }
            if record is not None and not result.skipped:
                row["stale"] = (
                    record.payable_days != result.payable_days
                    or record.net_pay != result.net_pay
                )
        rows.append(row)
    return rows


def _summarise(rows):
    totals = {"gross": ZERO, "deductions": ZERO, "net": ZERO}
    counts = {"locked": 0, "draft": 0, "new": 0, "skipped": 0, "provisional": 0}
    for row in rows:
        counts[row["state"]] += 1
        if row["result"].provisional and not row["locked"]:
            counts["provisional"] += 1
        if row["figures"]:
            totals["gross"] += row["figures"]["gross_earned"]
            totals["deductions"] += row["figures"]["total_deductions"]
            totals["net"] += row["figures"]["net_pay"]
    return totals, counts


# ──────────────────────────────────────────────────────────────────────────
# Actions
# ──────────────────────────────────────────────────────────────────────────
def _apply_action(request, action, rows, year, month):
    """Run calculate / lock / unlock on `rows`, reporting through messages."""
    label = rows[0]["result"].period_label if rows else f"{year}-{month:02d}"
    _, period_end = get_month_range(year, month)

    if not rows:
        messages.info(request, "There are no employees in view to act on.")
        return

    if action == "calculate":
        saved = locked = skipped = 0
        with transaction.atomic():
            for row in rows:
                if row["locked"]:
                    locked += 1
                elif row["result"].skipped:
                    skipped += 1
                else:
                    save_payroll_record(row["result"])
                    saved += 1
        parts = [f"Calculated and saved {saved} employee(s) for {label}."]
        if locked:
            parts.append(f"{locked} already locked (left unchanged).")
        if skipped:
            parts.append(f"{skipped} skipped (see reasons in the table).")
        messages.success(request, " ".join(parts))

    elif action == "lock":
        today = timezone.localdate()
        if period_end >= today:
            messages.error(
                request,
                f"{label} can't be locked until the month has ended "
                f"(after {period_end:%d %b %Y}). You can still calculate drafts.",
            )
            return
        newly = already = skipped = with_warnings = 0
        try:
            with transaction.atomic():
                for row in rows:
                    if row["locked"]:
                        already += 1
                    elif row["result"].skipped:
                        skipped += 1
                    else:
                        record = save_payroll_record(row["result"])
                        record.lock(request.user)
                        newly += 1
                        if row["result"].warnings:
                            with_warnings += 1
        except ValidationError as exc:
            messages.error(request, f"Nothing was locked: {exc.messages[0]}")
            return
        parts = [f"Locked payroll for {newly} employee(s) for {label}."]
        if already:
            parts.append(f"{already} were already locked.")
        if skipped:
            parts.append(f"{skipped} skipped (no payroll to lock).")
        if with_warnings:
            parts.append(f"{with_warnings} locked with warnings, please review.")
        messages.success(request, " ".join(parts))

    elif action == "unlock":
        count = 0
        with transaction.atomic():
            for row in rows:
                if row["locked"]:
                    row["record"].unlock()
                    count += 1
        if count:
            messages.warning(
                request,
                f"Unlocked {count} record(s) for {label}. Their figures will follow "
                "current attendance again until you lock them.",
            )
        else:
            messages.info(request, "None of the employees in view were locked.")


def _handle_post(request, rows, year, month):
    action = request.POST.get("action")
    if action not in ACTIONS:
        messages.error(request, "Unknown action.")
        return
    _apply_action(request, action, rows, year, month)


# ──────────────────────────────────────────────────────────────────────────
# Views
# ──────────────────────────────────────────────────────────────────────────
@login_required
def payroll_index_view(request):
    denied = _guard(request)
    if denied:
        return denied

    year = month = None
    raw = (request.GET.get("month") or "").strip()  # from <input type="month">
    if raw:
        try:
            y, m = raw.split("-")
            year, month = int(y), int(m)
            _validate_month(year, month)
        except (ValueError, Http404):
            year = month = None
            messages.error(request, "That isn't a valid month.")
    if year is None:
        year, month = _previous_month(timezone.localdate())

    url = reverse("payrollCycle", args=[year, month])
    project = (request.GET.get("project") or "").strip()
    return redirect(f"{url}?project={project}" if project else url)


@login_required
def payroll_cycle_view(request, year, month):
    denied = _guard(request)
    if denied:
        return denied
    _validate_month(year, month)

    project_ctx = project_filter_context(request)
    employees = _month_employees(request, year, month, project_ctx["project_filter_selected"])
    rows = _build_rows(employees, year, month)

    if request.method == "POST":
        _handle_post(request, rows, year, month)
        return redirect(request.get_full_path())

    totals, counts = _summarise(rows)
    period_start, period_end = get_month_range(year, month)
    today = timezone.localdate()
    prev_year, prev_month = _shift_month(year, month, -1)
    next_year, next_month = _shift_month(year, month, 1)

    return render(
        request,
        "appEmp/payroll_cycle.html",
        {
            "rows": rows,
            "totals": totals,
            "counts": counts,
            "year": year,
            "month": month,
            "month_label": period_start.strftime("%B %Y"),
            "month_value": f"{year:04d}-{month:02d}",
            "period_start": period_start,
            "period_end": period_end,
            "month_over": period_end < today,
            "prev_url": reverse("payrollCycle", args=[prev_year, prev_month]),
            "next_url": reverse("payrollCycle", args=[next_year, next_month]),
            "querystring": (
                f"?project={project_ctx['project_filter_selected']}"
                if project_ctx["project_filter_selected"]
                else ""
            ),
            **project_ctx,
        },
    )


@login_required
def payroll_employee_view(request, year, month, uuid):
    denied = _guard(request)
    if denied:
        return denied
    _validate_month(year, month)

    employee = get_object_or_404(
        empProfile.objects.select_related("user", "designation", "project"),
        uuid=uuid,
        organization=request.current_org,
    )
    rows = _build_rows([employee], year, month)

    if request.method == "POST":
        _handle_post(request, rows, year, month)
        return redirect(request.get_full_path())

    if not rows:
        raise Http404("This employee has no payroll for the selected month.")
    row = rows[0]
    period_start, period_end = get_month_range(year, month)

    # Money lines: the snapshot when locked, otherwise the live calculation.
    result, record = row["result"], row["record"]
    if row["locked"]:
        basic_earned, hra_earned = earned_split(record)
        money = {
            "basic_salary": record.basic_salary,
            "hra": record.hra,
            "gross_monthly": record.gross_monthly,
            "basic_earned": basic_earned,
            "hra_earned": hra_earned,
            "gross_earned": record.gross_earned,
            "pf": record.pf,
            "esi": record.esi,
            "other_deductions": record.other_deductions,
            "tds": record.tds,
            "total_deductions": record.total_deductions,
            "net_pay": record.net_pay,
        }
    elif not result.skipped:
        money = {
            name: getattr(result, name)
            for name in (
                "basic_salary", "hra", "gross_monthly", "basic_earned", "hra_earned",
                "gross_earned", "pf", "esi", "other_deductions", "tds",
                "total_deductions", "net_pay",
            )
        }
    else:
        money = None

    return render(
        request,
        "appEmp/payroll_employee.html",
        {
            "row": row,
            "employee": employee,
            "result": result,
            "record": record,
            "money": money,
            "year": year,
            "month": month,
            "month_label": period_start.strftime("%B %Y"),
            "period_start": period_start,
            "period_end": period_end,
            "month_over": period_end < timezone.localdate(),
            "back_url": reverse("payrollCycle", args=[year, month]),
        },
    )


# ──────────────────────────────────────────────────────────────────────────
# PDFs and employee self-service (Phase 4)
# Payslips and the summary are built from LOCKED records only.
# ──────────────────────────────────────────────────────────────────────────
def _pdf_response(buffer, filename):
    response = HttpResponse(buffer, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _payslip_filename(employee, year, month):
    who = slugify(employee.user.get_full_name() or employee.user.username) or "employee"
    return f"payslip_{who}_{year}_{month:02d}.pdf"


@login_required
def payroll_payslip_view(request, year, month, uuid):
    """Payslip PDF for any employee in the organization (payroll managers)."""
    denied = _guard(request)
    if denied:
        return denied
    _validate_month(year, month)

    employee = get_object_or_404(
        empProfile.objects.select_related("user", "designation"),
        uuid=uuid,
        organization=request.current_org,
    )
    record = (
        PayrollRecord.objects.select_related(
            "organization", "employee__user", "employee__designation"
        )
        .filter(employee=employee, year=year, month=month, is_locked=True)
        .first()
    )
    if record is None:
        messages.error(
            request,
            "A payslip is available only after payroll for this month has been locked.",
        )
        return redirect("payrollEmployee", year=year, month=month, uuid=employee.uuid)

    return _pdf_response(build_payslip_pdf(record), _payslip_filename(employee, year, month))


@login_required
def payroll_summary_pdf_view(request, year, month):
    """Month register of locked payroll, respecting the project filter."""
    denied = _guard(request)
    if denied:
        return denied
    _validate_month(year, month)

    project_ctx = project_filter_context(request)
    selected = project_ctx["project_filter_selected"]
    records = list(
        apply_project_filter(
            PayrollRecord.objects.filter(
                organization=request.current_org, year=year, month=month, is_locked=True
            ).select_related("employee__user", "employee__designation", "organization"),
            selected,
            path="employee__project",
        ).order_by("employee__user__first_name", "employee__user__last_name", "pk")
    )
    if not records:
        messages.error(request, "There is no locked payroll to summarise for this month.")
        target = reverse("payrollCycle", args=[year, month])
        return redirect(f"{target}?project={selected}" if selected else target)

    project_label = "Selected project filter" if selected else "All projects"
    buffer = build_payroll_summary_pdf(
        records, request.current_org.name, year, month, project_label
    )
    return _pdf_response(buffer, f"payroll_summary_{year}_{month:02d}.pdf")


def _own_profile(request):
    qs = empProfile.objects.select_related("organization", "user", "designation").filter(
        user=request.user
    )
    org = getattr(request, "current_org", None)
    if org is not None:
        qs = qs.filter(organization=org)
    return qs.first()


@login_required
def my_payslips_view(request):
    """The signed-in employee's own finalised payslips, newest first."""
    profile = _own_profile(request)
    if profile is None:
        messages.error(request, "You don't have an employee profile.")
        return redirect("dashboard")

    records = PayrollRecord.objects.filter(employee=profile, is_locked=True).order_by(
        "-year", "-month"
    )
    return render(
        request,
        "appEmp/my_payslips.html",
        {"records": list(records), "profile": profile},
    )


@login_required
def my_payslip_pdf_view(request, year, month):
    """Download the signed-in employee's own payslip for a finalised month."""
    _validate_month(year, month)
    profile = _own_profile(request)
    if profile is None:
        messages.error(request, "You don't have an employee profile.")
        return redirect("dashboard")

    record = (
        PayrollRecord.objects.select_related(
            "organization", "employee__user", "employee__designation"
        )
        .filter(employee=profile, year=year, month=month, is_locked=True)
        .first()
    )
    if record is None:
        messages.error(
            request,
            "That payslip isn't available yet. Payslips appear here once HR finalises payroll.",
        )
        return redirect("myPayslips")

    return _pdf_response(build_payslip_pdf(record), _payslip_filename(profile, year, month))
