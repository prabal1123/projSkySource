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

from .bank_file import split_for_bank, write_bank_csv
from .ecr import ecr_line, split_for_ecr
from .esi_return import build_esi_workbook, split_for_esi
from .settlement_pdf import build_settlement_pdf
from .models import (
    EmployeeExitRequest,
    FinalSettlement,
    FinalSettlementItem,
    FinalSettlementLog,
    PayrollAuditLog,
    PayrollRecord,
    empProfile,
)
from .payslip_pdf import build_payroll_summary_pdf, build_payslip_pdf
from .payroll_service import (
    calculate_payroll_for_employees,
    earned_components,
    get_month_range,
    save_payroll_record,
)

ZERO = Decimal("0")
ACTIONS = {"calculate", "lock", "unlock"}
MIN_UNLOCK_REASON = 10
MAX_UNLOCK_REASON = 255


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
                        PayrollAuditLog.record_event(
                            record, PayrollAuditLog.ACTION_LOCKED, request.user
                        )
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
        to_unlock = [row for row in rows if row["locked"]]
        reason = (request.POST.get("reason") or "").strip()
        if to_unlock and not (MIN_UNLOCK_REASON <= len(reason) <= MAX_UNLOCK_REASON):
            messages.error(
                request,
                f"Give a reason of {MIN_UNLOCK_REASON} to {MAX_UNLOCK_REASON} characters "
                "to unlock payroll. Nothing was unlocked.",
            )
            return
        count = 0
        with transaction.atomic():
            for row in to_unlock:
                row["record"].unlock()
                PayrollAuditLog.record_event(
                    row["record"], PayrollAuditLog.ACTION_UNLOCKED, request.user, reason
                )
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
        parts = earned_components(record)
        money = {
            "basic_salary": record.basic_salary,
            "hra": record.hra,
            "da": record.da,
            "special_allowance": record.special_allowance,
            "other_allowances": record.other_allowances,
            "gross_monthly": record.gross_monthly,
            "basic_earned": parts["basic"],
            "hra_earned": parts["hra"],
            "da_earned": parts["da"],
            "special_earned": parts["special"],
            "other_earned": parts["other"],
            "statutory_wages": record.statutory_wages,
            "gross_earned": record.gross_earned,
            "pf": record.pf,
            "esi": record.esi,
            "other_deductions": record.other_deductions,
            "tds": record.tds,
            "professional_tax": record.professional_tax,
            "deferred_deductions": record.deferred_deductions,
            "total_deductions": record.total_deductions,
            "net_pay": record.net_pay,
        }
    elif not result.skipped:
        money = {
            name: getattr(result, name)
            for name in (
                "basic_salary", "hra", "da", "special_allowance", "other_allowances",
                "gross_monthly", "basic_earned", "hra_earned", "da_earned",
                "special_earned", "other_earned", "statutory_wages",
                "gross_earned", "pf", "esi", "other_deductions", "tds",
                "professional_tax", "deferred_deductions", "total_deductions", "net_pay",
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


@login_required
def payroll_bank_file_view(request, year, month):
    """Generic NEFT CSV of the month's locked payroll, respecting the project filter."""
    denied = _guard(request)
    if denied:
        return denied
    _validate_month(year, month)

    project_ctx = project_filter_context(request)
    selected = project_ctx["project_filter_selected"]
    target = reverse("payrollCycle", args=[year, month])
    back = redirect(f"{target}?project={selected}" if selected else target)

    records = list(
        apply_project_filter(
            PayrollRecord.objects.filter(
                organization=request.current_org, year=year, month=month, is_locked=True
            ).select_related("employee__user", "organization"),
            selected,
            path="employee__project",
        ).order_by("employee__user__first_name", "employee__user__last_name", "pk")
    )
    if not records:
        messages.error(request, "There is no locked payroll to export for this month.")
        return back

    included, left_out = split_for_bank(records)
    if not included:
        messages.error(
            request,
            "No bank file was made: none of the locked employees has complete bank "
            "details and a net pay above zero.",
        )
        return back

    with transaction.atomic():
        for record, _details in included:
            PayrollAuditLog.record_event(
                record, PayrollAuditLog.ACTION_EXPORTED, request.user, "Bank file (NEFT CSV)"
            )

    if left_out:
        shown = "; ".join(f"{name} ({why})" for name, why in left_out[:5])
        more = f" and {len(left_out) - 5} more" if len(left_out) > 5 else ""
        messages.warning(
            request,
            f"{len(left_out)} employee(s) were left out of the bank file: {shown}{more}.",
        )

    start, _end = get_month_range(year, month)
    narration = f"Salary {start:%b %Y}"
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="bank_file_{slugify(request.current_org.name)}_{year}_{month:02d}.csv"'
    )
    write_bank_csv(response, included, narration)
    return response


@login_required
def payroll_ecr_view(request, year, month):
    """PF ECR text file of the month's locked payroll, respecting the project filter."""
    denied = _guard(request)
    if denied:
        return denied
    _validate_month(year, month)

    project_ctx = project_filter_context(request)
    selected = project_ctx["project_filter_selected"]
    target = reverse("payrollCycle", args=[year, month])
    back = redirect(f"{target}?project={selected}" if selected else target)

    records = list(
        apply_project_filter(
            PayrollRecord.objects.filter(
                organization=request.current_org, year=year, month=month, is_locked=True
            ).select_related("employee__user", "organization"),
            selected,
            path="employee__project",
        ).order_by("employee__user__first_name", "employee__user__last_name", "pk")
    )
    if not records:
        messages.error(request, "There is no locked payroll to export for this month.")
        return back

    included, left_out = split_for_ecr(records)
    if not included:
        messages.error(
            request,
            "No ECR was made: no locked employee has PF for this month together with a valid UAN.",
        )
        return back

    with transaction.atomic():
        for record, _details in included:
            PayrollAuditLog.record_event(
                record, PayrollAuditLog.ACTION_EXPORTED, request.user, "PF ECR"
            )

    if left_out:
        shown = "; ".join(f"{name} ({why})" for name, why in left_out[:5])
        more = f" and {len(left_out) - 5} more" if len(left_out) > 5 else ""
        messages.warning(
            request,
            f"{len(left_out)} member(s) were left out of the ECR: {shown}{more}.",
        )

    text = "\n".join(ecr_line(record, details) for record, details in included) + "\n"
    response = HttpResponse(text, content_type="text/plain")
    response["Content-Disposition"] = (
        f'attachment; filename="ECR_{slugify(request.current_org.name)}_{year}_{month:02d}.txt"'
    )
    return response


@login_required
def payroll_esi_return_view(request, year, month):
    """ESI monthly contribution Excel of the month's locked payroll, respecting the project filter."""
    denied = _guard(request)
    if denied:
        return denied
    _validate_month(year, month)

    project_ctx = project_filter_context(request)
    selected = project_ctx["project_filter_selected"]
    target = reverse("payrollCycle", args=[year, month])
    back = redirect(f"{target}?project={selected}" if selected else target)

    records = list(
        apply_project_filter(
            PayrollRecord.objects.filter(
                organization=request.current_org, year=year, month=month, is_locked=True
            ).select_related("employee__user", "organization"),
            selected,
            path="employee__project",
        ).order_by("employee__user__first_name", "employee__user__last_name", "pk")
    )
    if not records:
        messages.error(request, "There is no locked payroll to export for this month.")
        return back

    exit_dates = {}
    for emp_id, last_day in (
        EmployeeExitRequest.objects.filter(
            employee_id__in=[r.employee_id for r in records],
            status="COMPLETED",
            final_last_working_date__isnull=False,
        )
        .order_by("created_at")
        .values_list("employee_id", "final_last_working_date")
    ):
        exit_dates[emp_id] = last_day

    included, left_out = split_for_esi(records, exit_dates)
    if not included:
        messages.error(
            request,
            "No ESI return was made: no locked employee has ESI for this month together "
            "with a valid ESIC number.",
        )
        return back

    with transaction.atomic():
        for record, _details in included:
            PayrollAuditLog.record_event(
                record, PayrollAuditLog.ACTION_EXPORTED, request.user, "ESI return"
            )

    if left_out:
        shown = "; ".join(f"{name} ({why})" for name, why in left_out[:5])
        more = f" and {len(left_out) - 5} more" if len(left_out) > 5 else ""
        messages.warning(
            request,
            f"{len(left_out)} employee(s) were left out of the ESI return: {shown}{more}.",
        )

    response = HttpResponse(
        build_esi_workbook(included),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="ESI_{slugify(request.current_org.name)}_{year}_{month:02d}.xlsx"'
    )
    return response


SETTLEMENT_EXIT_STATUSES = ("READY_FOR_FINALIZATION", "COMPLETED")


def _settlement_reference(exit_request):
    """The final month's payroll, shown on the settlement as a reference only."""
    last = exit_request.final_last_working_date or exit_request.proposed_last_working_date
    if not last:
        return None
    record = PayrollRecord.objects.filter(
        employee=exit_request.employee, year=last.year, month=last.month
    ).first()
    locked = record is not None and record.is_locked
    return {
        "label": f"{last:%B %Y}",
        "locked": locked,
        "net_pay": record.net_pay if locked else None,
    }


def _settlement_action(request, exit_request, settlement):
    from decimal import InvalidOperation

    action = request.POST.get("action")

    if action == "create":
        if settlement is not None:
            messages.info(request, "A settlement already exists for this exit.")
        elif exit_request.status not in SETTLEMENT_EXIT_STATUSES:
            messages.error(request, "A settlement can be started once the exit is ready for finalization.")
        else:
            with transaction.atomic():
                created = FinalSettlement.objects.create(
                    exit_request=exit_request, employee=exit_request.employee
                )
                FinalSettlementLog.record_event(
                    created, FinalSettlementLog.ACTION_CREATED, request.user
                )
            messages.success(request, "Settlement started. Add its items below.")
        return

    if settlement is None:
        messages.error(request, "Start the settlement first.")
        return

    if action == "add_item":
        if settlement.status != FinalSettlement.STATUS_DRAFT:
            messages.error(request, "Items can only be changed while the settlement is a draft.")
            return
        kind = request.POST.get("kind")
        label = (request.POST.get("label") or "").strip()
        note = (request.POST.get("note") or "").strip()[:255]
        try:
            amount = Decimal((request.POST.get("amount") or "").strip())
        except InvalidOperation:
            amount = None
        if kind not in (FinalSettlementItem.KIND_EARNING, FinalSettlementItem.KIND_DEDUCTION):
            messages.error(request, "Choose whether the item is an earning or a deduction.")
        elif not label or len(label) > 100:
            messages.error(request, "Give the item a name of up to 100 characters.")
        elif amount is None or not amount.is_finite() or amount <= 0 or amount >= Decimal("10000000000"):
            messages.error(request, "Enter an amount above zero.")
        else:
            FinalSettlementItem.objects.create(
                settlement=settlement, kind=kind, label=label,
                amount=amount.quantize(Decimal("0.01")), note=note,
            )
            messages.success(request, "Item added.")

    elif action == "delete_item":
        if settlement.status != FinalSettlement.STATUS_DRAFT:
            messages.error(request, "Items can only be changed while the settlement is a draft.")
            return
        try:
            item_id = int(request.POST.get("item") or 0)
        except ValueError:
            item_id = 0
        item = settlement.items.filter(pk=item_id).first()
        if item is None:
            messages.error(request, "That item was not found.")
        else:
            item.delete()
            messages.success(request, "Item removed.")

    elif action == "approve":
        if settlement.status != FinalSettlement.STATUS_DRAFT:
            messages.info(request, "This settlement is already approved.")
        elif not settlement.items.exists():
            messages.error(request, "Add at least one item before approving.")
        else:
            with transaction.atomic():
                settlement.approve(request.user)
                FinalSettlementLog.record_event(
                    settlement, FinalSettlementLog.ACTION_APPROVED, request.user
                )
            messages.success(request, "Settlement approved.")

    elif action == "paid":
        if settlement.status != FinalSettlement.STATUS_APPROVED:
            messages.error(request, "Only an approved settlement can be marked as paid.")
        else:
            with transaction.atomic():
                settlement.mark_paid()
                FinalSettlementLog.record_event(
                    settlement, FinalSettlementLog.ACTION_PAID, request.user
                )
            messages.success(request, "Settlement marked as paid.")

    elif action == "unlock":
        reason = (request.POST.get("reason") or "").strip()
        if settlement.status != FinalSettlement.STATUS_APPROVED:
            messages.error(request, "Only an approved settlement that is not paid can be unlocked.")
        elif not (MIN_UNLOCK_REASON <= len(reason) <= MAX_UNLOCK_REASON):
            messages.error(
                request,
                f"Give a reason of {MIN_UNLOCK_REASON} to {MAX_UNLOCK_REASON} characters. "
                "Nothing was unlocked.",
            )
        else:
            with transaction.atomic():
                settlement.unlock()
                FinalSettlementLog.record_event(
                    settlement, FinalSettlementLog.ACTION_UNLOCKED, request.user, reason
                )
            messages.warning(request, "Settlement unlocked. Its items can be changed again.")
    else:
        messages.error(request, "Unknown action.")


@login_required
def final_settlement_view(request, uuid):
    denied = _guard(request)
    if denied:
        return denied
    exit_request = get_object_or_404(
        EmployeeExitRequest.objects.select_related("employee__user"),
        uuid=uuid,
        employee__organization=request.current_org,
    )
    settlement = FinalSettlement.objects.filter(exit_request=exit_request).first()

    if request.method == "POST":
        _settlement_action(request, exit_request, settlement)
        return redirect("finalSettlement", uuid=exit_request.uuid)

    items = list(settlement.items.all()) if settlement else []
    net = settlement.net_payable if settlement else ZERO
    return render(
        request,
        "appEmp/final_settlement.html",
        {
            "exit_request": exit_request,
            "settlement": settlement,
            "items": items,
            "logs": list(settlement.logs.all()[:20]) if settlement else [],
            "total_earnings": settlement.total_earnings if settlement else ZERO,
            "total_deductions": settlement.total_deductions if settlement else ZERO,
            "recoverable": net < 0,
            "net_abs": abs(net),
            "reference": _settlement_reference(exit_request),
            "last_day": exit_request.final_last_working_date or exit_request.proposed_last_working_date,
            "can_create": exit_request.status in SETTLEMENT_EXIT_STATUSES,
        },
    )


@login_required
def final_settlement_pdf_view(request, uuid):
    denied = _guard(request)
    if denied:
        return denied
    settlement = get_object_or_404(
        FinalSettlement.objects.select_related(
            "employee__user", "exit_request", "organization"
        ),
        exit_request__uuid=uuid,
        organization=request.current_org,
    )
    if settlement.status == FinalSettlement.STATUS_DRAFT:
        messages.error(request, "Approve the settlement before downloading its statement.")
        return redirect("finalSettlement", uuid=uuid)
    buffer = build_settlement_pdf(settlement, _settlement_reference(settlement.exit_request))
    name = slugify(settlement.employee.user.get_username())
    return _pdf_response(buffer, f"settlement_{name}.pdf")


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
