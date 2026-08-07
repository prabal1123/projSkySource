import calendar
from io import BytesIO

from django.contrib import messages
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.utils import timezone
from django.db.models import Count, Q
from datetime import date

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from django.urls import reverse
from .models import empProfile, Attendance, ADMIN_ROLES, LATE_CUTOFF_TIME, Salary, LeaveRequest,LeaveBalance,LeaveTypeMaster,AttendanceException
from .forms import EmployeeForm, ProfileFormAdmin, AttendanceUpdateForm, SalaryForm,AttendanceException
from .forms import LeaveBalanceForm,AttendanceExceptionForm,LeaveRequestForm,LeaveRequestReviewForm
from django.db import transaction
from django.db.models import F
from django.urls import reverse
from datetime import timedelta
from .forms import AttendanceExceptionReviewForm

@login_required
def empList_view(request):
    objects = empProfile.objects.values("id","user__first_name", "user__last_name", "phone_number", "uuid")

    return render(request, "appEmp/empList.html", {"objects": objects})

# @login_required
# def profileDetail_view(request, uuid):
#     employee = get_object_or_404(empProfile, uuid=uuid)

#     if request.method == "POST":
#         form = ProfileFormAdmin(request.POST, instance=employee)
#         if form.is_valid():
#             form.save()
#             messages.success(request, "Profile updated successfully.")
#             return redirect("editProfile", uuid=employee.uuid)
#     else:
#         form = ProfileFormAdmin(instance=employee)

#     target_salary = employee.salary_records.filter(is_active=True).first()

#     return render(
#         request,
#         "appEmp/profile.html",
#         {
#             "employee": employee,
#             "profile": employee,
#             "form": form,
#             "salary": target_salary,
#             "can_edit_salary": True,
#             "salary_form": SalaryForm(instance=target_salary),
#             "target_uuid": employee.uuid,
#             "current_year": timezone.now().year,
#             "current_month": timezone.now().month,
#         },
#     )

@login_required
def profileDetail_view(request, uuid):
    logged_in_profile = get_object_or_404(
        empProfile,
        user=request.user
    )

    employee = get_object_or_404(
        empProfile.objects.select_related(
            "user",
            "manager__user",
            "designation",
            "shift",
        ),
        uuid=uuid,
    )

    is_admin = logged_in_profile.role in ADMIN_ROLES
    is_direct_manager = employee.manager_id == logged_in_profile.id

    if not is_admin and not is_direct_manager:
        messages.error(
            request,
            "You don't have permission to edit this employee profile."
        )
        return redirect("dashboard")

    if request.method == "POST":
        form = ProfileFormAdmin(
            request.POST,
            instance=employee
        )

        if form.is_valid():
            form.save()

            messages.success(
                request,
                "Profile updated successfully."
            )

            return redirect(
                "editProfile",
                uuid=employee.uuid
            )
    else:
        form = ProfileFormAdmin(
            instance=employee
        )

    target_salary = employee.salary_records.filter(
        is_active=True
    ).first()

    return render(
        request,
        "appEmp/profile.html",
        {
            "employee": employee,
            "profile": employee,
            "form": form,
            "salary": target_salary,
            "can_edit_salary": is_admin,
            "can_edit_profile": True,
            "salary_form": SalaryForm(
                instance=target_salary
            ),
            "target_uuid": employee.uuid,
            "current_year": timezone.now().year,
            "current_month": timezone.now().month,
        },
    )


@login_required
def empProfile_view(request):
    profile, created = empProfile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = EmployeeForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully.")
            return redirect("myProfile")
    else:
        form = EmployeeForm(instance=profile)

    self_salary = profile.salary_records.filter(is_active=True).first()

    return render(
        request,
        "appEmp/profile.html",
        {
            "form": form,
            "profile": profile,
            "created": created,
            "salary": self_salary,
            "can_edit_salary": False,
            "target_uuid": profile.uuid,
            "current_year": timezone.now().year,
            "current_month": timezone.now().month,
        },
    )

@login_required
# def dashboard_view(request):
#     profile = get_object_or_404(empProfile, user=request.user)
#     today = timezone.localdate()

#     if profile.role in ADMIN_ROLES:
#         total_employees = empProfile.objects.count()

#         verification_stats = {
#             "email": empProfile.objects.filter(is_email_verified=True).count(),
#             "phone": empProfile.objects.filter(is_phone_verified=True).count(),
#             "address": empProfile.objects.filter(is_address_verified=True).count(),
#             "aadhar": empProfile.objects.filter(is_aadhar_verified=True).count(),
#             "background_check": empProfile.objects.filter(is_background_check_completed=True).count(),
#         }

#         today_attendance = Attendance.objects.filter(date=today)
#         attendance_summary = {
#             "present": today_attendance.filter(status__in=['PRESENT', 'LATE', 'HALF_DAY']).count(),
#             "absent": today_attendance.filter(status='ABSENT').count(),
#             "leave": today_attendance.filter(status='LEAVE').count(),
#             "not_marked": total_employees - today_attendance.count(),
#         }

#         context = {
#             "is_admin_view": True,
#             "total_employees": total_employees,
#             "verification_stats": verification_stats,
#             "attendance_summary": attendance_summary,
#             "today_attendance": today_attendance.select_related('employee__user'),
#         }
#     else:
#         my_attendance_today = Attendance.objects.filter(employee=profile, date=today).first()
#         recent_attendance = Attendance.objects.filter(employee=profile).order_by('-date')[:7]

#         context = {
#             "is_admin_view": False,
#             "profile": profile,
#             "my_attendance_today": my_attendance_today,
#             "recent_attendance": recent_attendance,
#         }

#     return render(request, "dashboard.html", context)

@login_required
def dashboard_view(request):
    profile = get_object_or_404(
        empProfile,
        user=request.user
    )

    today = timezone.localdate()

    if profile.role in ADMIN_ROLES:
        total_employees = empProfile.objects.count()

        verification_stats = {
            "email": empProfile.objects.filter(
                is_email_verified=True
            ).count(),

            "phone": empProfile.objects.filter(
                is_phone_verified=True
            ).count(),

            "address": empProfile.objects.filter(
                is_address_verified=True
            ).count(),

            "aadhar": empProfile.objects.filter(
                is_aadhar_verified=True
            ).count(),

            "background_check": empProfile.objects.filter(
                is_background_check_completed=True
            ).count(),
        }

        today_attendance = Attendance.objects.filter(
            date=today
        )

        attendance_summary = {
            "present": today_attendance.filter(
                status__in=[
                    "PRESENT",
                    "LATE",
                    "HALF_DAY",
                ]
            ).count(),

            "absent": today_attendance.filter(
                status="ABSENT"
            ).count(),

            "leave": today_attendance.filter(
                status="LEAVE"
            ).count(),

            "not_marked": (
                total_employees
                - today_attendance.count()
            ),
        }

        # ── HR Action Required ──────────────────────────────

        pending_leave_requests_count = (
            LeaveRequest.objects
            .filter(status="PENDING")
            .count()
        )

        pending_attendance_exceptions_count = (
            AttendanceException.objects
            .filter(status="PENDING")
            .count()
        )

        current_year = today.year

        employees_without_leave_balance = (
            empProfile.objects
            .filter(is_active=True)
            .exclude(
                leave_balances__year=current_year
            )
            .distinct()
            .count()
        )

        context = {
            "is_admin_view": True,

            "total_employees": total_employees,

            "verification_stats": verification_stats,

            "attendance_summary": attendance_summary,

            "today_attendance": (
                today_attendance.select_related(
                    "employee__user"
                )
            ),

            # Action Required counts
            "pending_leave_requests_count": (
                pending_leave_requests_count
            ),

            "pending_attendance_exceptions_count": (
                pending_attendance_exceptions_count
            ),

            "employees_without_leave_balance": (
                employees_without_leave_balance
            ),
        }

    else:
        my_attendance_today = (
            Attendance.objects
            .filter(
                employee=profile,
                date=today
            )
            .first()
        )

        recent_attendance = (
            Attendance.objects
            .filter(employee=profile)
            .order_by("-date")[:7]
        )

        context = {
            "is_admin_view": False,

            "profile": profile,

            "my_attendance_today": (
                my_attendance_today
            ),

            "recent_attendance": (
                recent_attendance
            ),
        }

    return render(
        request,
        "dashboard.html",
        context
    )


@login_required
def checkin_checkout_view(request):
    profile = get_object_or_404(empProfile, user=request.user)
    today = timezone.localdate()
    now = timezone.localtime()

    attendance, created = Attendance.objects.get_or_create(employee=profile, date=today)

    if attendance.check_in is None:
        attendance.check_in = now
        attendance.status = 'LATE' if now.time() > LATE_CUTOFF_TIME else 'PRESENT'
        attendance.save()
        messages.success(request, f"Checked in at {now.strftime('%I:%M %p')}.")
    elif attendance.check_out is None:
        attendance.check_out = now
        attendance.save()
        messages.success(request, f"Checked out at {now.strftime('%I:%M %p')}.")
    else:
        messages.info(request, "You've already checked in and out today.")

    return redirect('dashboard')


@login_required
def update_attendance_view(request, uuid):
    profile = get_object_or_404(empProfile, user=request.user)
    if profile.role not in ADMIN_ROLES:
        messages.error(request, "You don't have permission to do that.")
        return redirect('dashboard')

    attendance = get_object_or_404(Attendance, uuid=uuid)

    if request.method == "POST":
        form = AttendanceUpdateForm(request.POST, instance=attendance)
        if form.is_valid():
            record = form.save(commit=False)
            record.marked_by = request.user
            record.save()
            messages.success(request, f"Attendance updated for {attendance.employee}.")
            return redirect('dashboard')
    else:
        form = AttendanceUpdateForm(instance=attendance)

    return render(request, "appEmp/edit_attendance.html", {"form": form, "attendance": attendance})


@login_required
def salary_update_view(request, uuid):
    """
    POST-only endpoint. HR/Admin submits the salary form embedded in
    profile.html (via _salary_block.html) and gets redirected straight
    back to that same profile page. Deliberately kept separate from your
    existing profileDetail_view POST handling so this patch doesn't touch
    code I can't see.
    """
    profile_check = request.user.empprofile  # adjust related name if yours differs
    if profile_check.role not in ADMIN_ROLES:
        messages.error(request, "You don't have permission to do this.")
        return redirect('dashboard')

    target = get_object_or_404(empProfile, uuid=uuid)

    if request.method == 'POST':
        form = SalaryForm(request.POST)
        if form.is_valid():
            new_salary = form.save(commit=False)
            new_salary.employee = target
            new_salary.is_active = True
            new_salary.created_by = request.user
            new_salary.save()
            messages.success(
                request,
                f"Salary updated for {target.user.get_full_name() or target.user.username}."
            )
        else:
            messages.error(request, "Please correct the errors in the salary form.")

    # Change 'profileDetail' below to whatever your actual profileDetail_view
    # url name is (check appEmp/urls.py).
    return redirect('editProfile', uuid=target.uuid)


def _build_salary_slip_pdf(salary, profile, month, year):
    """Renders a salary slip to an in-memory PDF buffer using ReportLab
    (no system dependencies needed, unlike WeasyPrint)."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=20 * mm, bottomMargin=20 * mm,
        leftMargin=20 * mm, rightMargin=20 * mm,
    )
    styles = getSampleStyleSheet()
    elements = []

    NAVY = colors.HexColor('#0F172A')
    TEAL = colors.HexColor('#0F9E96')
    ROSE = colors.HexColor('#9F1239')
    GRID = colors.HexColor('#CBD5E1')

    title_style = ParagraphStyle('SlipTitle', parent=styles['Heading1'], textColor=NAVY, spaceAfter=2)
    elements.append(Paragraph("Salary Slip", title_style))
    elements.append(Paragraph(f"{calendar.month_name[month]} {year}", styles['Normal']))
    elements.append(Spacer(1, 8 * mm))

    emp_info = [
        ['Employee Name', profile.user.get_full_name() or profile.user.username],
        ['Employee ID', str(profile.uuid)[:8].upper()],
        ['Position', profile.position or '—'],
        ['Date of Joining', str(profile.date_hired) if profile.date_hired else '—'],
    ]
    t1 = Table(emp_info, colWidths=[55 * mm, 105 * mm])
    t1.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TEXTCOLOR', (0, 0), (0, -1), TEAL),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
    ]))
    elements.append(t1)
    elements.append(Spacer(1, 8 * mm))

    tds_monthly = salary.calculate_monthly_tds()
    net_pay = salary.net_monthly_pay

    earnings = [
        ['Earnings', 'Amount (INR)'],
        ['Basic Salary', f"{salary.basic_salary:,.2f}"],
        ['HRA', f"{salary.hra:,.2f}"],
        ['Gross Earnings', f"{salary.gross_monthly:,.2f}"],
    ]
    deductions = [
        ['Deductions', 'Amount (INR)'],
        ['Provident Fund (PF)', f"{salary.pf:,.2f}"],
        ['TDS (Tax Deducted at Source)', f"{tds_monthly:,.2f}"],
        ['Total Deductions', f"{(salary.pf + tds_monthly):,.2f}"],
    ]

    t2 = Table(earnings, colWidths=[110 * mm, 50 * mm])
    t2.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), NAVY),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, GRID),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
    ]))
    elements.append(t2)
    elements.append(Spacer(1, 6 * mm))

    t3 = Table(deductions, colWidths=[110 * mm, 50 * mm])
    t3.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), ROSE),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, GRID),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
    ]))
    elements.append(t3)
    elements.append(Spacer(1, 8 * mm))

    net_table = Table([['Net Pay', f"Rs. {net_pay:,.2f}"]], colWidths=[110 * mm, 50 * mm])
    net_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), TEAL),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
    ]))
    elements.append(net_table)
    elements.append(Spacer(1, 10 * mm))

    elements.append(Paragraph(
        "This is a system-generated salary slip. Tax figures shown are an estimate; "
        "refer to Form 16 issued by HR for final tax liability.",
        styles['Italic']
    ))

    doc.build(elements)
    buffer.seek(0)
    return buffer


@login_required
def salary_slip_self_view(request, year, month):
    profile = request.user.empprofile
    salary = profile.salary_records.filter(is_active=True).first()
    if not salary:
        messages.error(request, "No salary record found. Contact HR.")
        return redirect('myProfile')  # adjust to your actual self-profile url name

    buffer = _build_salary_slip_pdf(salary, profile, month, year)
    filename = f"salary_slip_{profile.user.username}_{year}_{month:02d}.pdf"
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def salary_slip_admin_view(request, uuid, year, month):
    profile_check = request.user.empprofile
    if profile_check.role not in ADMIN_ROLES: 
        messages.error(request, "You don't have permission to do this.")
        return redirect('dashboard')

    profile = get_object_or_404(empProfile, uuid=uuid)
    salary = profile.salary_records.filter(is_active=True).first()
    if not salary:
        messages.error(request, "No salary record found for this employee.")
        return redirect('editProfile', uuid=profile.uuid)  # adjust url name if needed

    buffer = _build_salary_slip_pdf(salary, profile, month, year)
    filename = f"salary_slip_{profile.user.username}_{year}_{month:02d}.pdf"
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

def _build_attendance_calendar(employee, year, month):
    month_calendar = calendar.Calendar(firstweekday=0)
    calendar_weeks = month_calendar.monthdatescalendar(year, month)

    first_day = date(year, month, 1)

    if month == 12:
        next_month_first_day = date(year + 1, 1, 1)
    else:
        next_month_first_day = date(year, month + 1, 1)

    attendance_records = list(
        Attendance.objects.filter(
            employee=employee,
            date__gte=first_day,
            date__lt=next_month_first_day,
        )
    )

    attendance_by_date = {
        record.date: record
        for record in attendance_records
    }

    attendance_ids = [
        record.id
        for record in attendance_records
    ]

    pending_exceptions = AttendanceException.objects.filter(
        attendance_id__in=attendance_ids,
        status="PENDING",
    )

    pending_exception_by_attendance = {
        exception.attendance_id: exception
        for exception in pending_exceptions
    }

    status_classes = {
        "PRESENT": "attendance-present",
        "LATE": "attendance-late",
        "HALF_DAY": "attendance-half-day",
        "ABSENT": "attendance-absent",
        "LEAVE": "attendance-leave",
    }

    weeks = []

    for week in calendar_weeks:
        week_data = []

        for day in week:
            attendance = attendance_by_date.get(day)

            pending_exception = None

            if attendance:
                pending_exception = (
                    pending_exception_by_attendance.get(attendance.id)
                )

            week_data.append({
                "date": day,
                "day_number": day.day,
                "is_current_month": day.month == month,
                "is_today": day == timezone.localdate(),
                "attendance": attendance,
                "pending_exception": pending_exception,
                "status_class": (
                    status_classes.get(attendance.status, "")
                    if attendance
                    else ""
                ),
            })

        weeks.append(week_data)

    if month == 1:
        previous_year = year - 1
        previous_month = 12
    else:
        previous_year = year
        previous_month = month - 1

    if month == 12:
        next_year = year + 1
        next_month = 1
    else:
        next_year = year
        next_month = month + 1

    return {
        "weeks": weeks,
        "month_name": calendar.month_name[month],
        "year": year,
        "month": month,
        "previous_year": previous_year,
        "previous_month": previous_month,
        "next_year": next_year,
        "next_month": next_month,
    }

@login_required
def attendance_calendar_self_view(request):
    """
    Employee apna attendance calendar dekhega.
    """

    employee = get_object_or_404(
        empProfile.objects.select_related(
            "user",
            "manager__user",
            "designation",
            "shift",
        ),
        user=request.user,
    )

    today = timezone.localdate()

    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
        selected_date = date(year, month, 1)
    except (TypeError, ValueError):
        year = today.year
        month = today.month
        selected_date = date(year, month, 1)

    calendar_data = _build_attendance_calendar(
        employee,
        selected_date.year,
        selected_date.month,
    )

    context = {
        "employee": employee,
        "is_admin_calendar": False,
        **calendar_data,
    }

    return render(
        request,
        "appEmp/attendance_calendar.html",
        context,
    )

@login_required
def raise_attendance_exception_view(request, attendance_uuid):
    employee = get_object_or_404(
        empProfile,
        user=request.user,
    )

    attendance = get_object_or_404(
        Attendance.objects.select_related("employee__user"),
        uuid=attendance_uuid,
        employee=employee,
    )

    calendar_url = reverse("attendanceCalendarSelf")
    calendar_redirect_url = (
        f"{calendar_url}"
        f"?year={attendance.date.year}"
        f"&month={attendance.date.month}"
    )

    if attendance.status != "ABSENT":
        messages.error(
            request,
            "An exception request can currently be raised only for an absent day."
        )
        return redirect(calendar_redirect_url)

    existing_pending_request = AttendanceException.objects.filter(
        attendance=attendance,
        raised_by=request.user,
        status="PENDING",
    ).exists()

    if existing_pending_request:
        messages.info(
            request,
            "A pending exception request already exists for this date."
        )
        return redirect(calendar_redirect_url)

    if request.method == "POST":
        form = AttendanceExceptionForm(request.POST)

        if form.is_valid():
            exception = form.save(commit=False)
            exception.attendance = attendance
            exception.raised_by = request.user
            exception.status = "PENDING"
            exception.save()

            messages.success(
                request,
                "Attendance exception request submitted successfully."
            )
            return redirect(calendar_redirect_url)
    else:
        form = AttendanceExceptionForm()

    return render(
        request,
        "appEmp/raise_attendance_exception.html",
        {
            "form": form,
            "attendance": attendance,
            "employee": employee,
        },
    )

@login_required
def attendance_calendar_admin_view(request, uuid):
    """
    HR/Admin kisi employee ka attendance calendar dekhega.
    Direct manager bhi apne team member ka calendar dekh sakta hai.
    """

    logged_in_profile = get_object_or_404(
        empProfile,
        user=request.user,
    )

    employee = get_object_or_404(
        empProfile.objects.select_related(
            "user",
            "manager__user",
            "designation",
            "shift",
        ),
        uuid=uuid,
    )

    is_admin = logged_in_profile.role in ADMIN_ROLES
    is_direct_manager = employee.manager_id == logged_in_profile.id

    if not is_admin and not is_direct_manager:
        messages.error(
            request,
            "You don't have permission to view this attendance calendar."
        )
        return redirect("dashboard")

    today = timezone.localdate()

    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
        selected_date = date(year, month, 1)
    except (TypeError, ValueError):
        year = today.year
        month = today.month
        selected_date = date(year, month, 1)

    calendar_data = _build_attendance_calendar(
        employee,
        selected_date.year,
        selected_date.month,
    )

    context = {
        "employee": employee,
        "is_admin_calendar": True,
        **calendar_data,
    }

    return render(
        request,
        "appEmp/attendance_calendar.html",
        context,
    )

# @login_required
# def apply_leave_view(request):
#     employee = get_object_or_404(
#         empProfile.objects.select_related("user", "manager__user"),
#         user=request.user,
#     )

#     if request.method == "POST":
#         form = LeaveRequestForm(
#             request.POST,
#             employee=employee,
#         )

#         if form.is_valid():
#             leave_request = form.save(commit=False)
#             leave_request.employee = employee
#             leave_request.status = "PENDING"
#             leave_request.save()

#             messages.success(
#                 request,
#                 "Leave request submitted successfully."
#             )

#             return redirect("myLeaveRequests")
#     else:
#         form = LeaveRequestForm(employee=employee)

#     current_year = timezone.localdate().year

#     balances = (
#         LeaveBalance.objects
#         .filter(employee=employee, year=current_year)
#         .select_related("leave_type")
#         .order_by("leave_type__name")
#     )

#     return render(
#         request,
#         "appEmp/apply_leave.html",
#         {
#             "form": form,
#             "employee": employee,
#             "balances": balances,
#             "current_year": current_year,
#         },
#     )

@login_required
def apply_leave_view(request):
    employee = get_object_or_404(
        empProfile.objects.select_related(
            "user",
            "manager__user"
        ),
        user=request.user,
    )

    if request.method == "POST":
        form = LeaveRequestForm(
            request.POST,
            employee=employee,
        )

        if form.is_valid():
            leave_request = form.save(commit=False)
            leave_request.employee = employee
            leave_request.status = "PENDING"
            leave_request.save()

            messages.success(
                request,
                "Leave request submitted successfully."
            )

            return redirect("myLeaveRequests")

        print("\n========== LEAVE FORM INVALID ==========")
        print("POST DATA:", request.POST)
        print("FORM ERRORS:")
        print(form.errors)
        print("NON FIELD ERRORS:")
        print(form.non_field_errors())
        print("CLEANED DATA:")
        print(form.cleaned_data)
        print("========================================\n")

    else:
        form = LeaveRequestForm(
            employee=employee
        )

    current_year = timezone.localdate().year

    balances = (
        LeaveBalance.objects
        .filter(
            employee=employee,
            year=current_year
        )
        .select_related("leave_type")
        .order_by("leave_type__name")
    )

    return render(
        request,
        "appEmp/apply_leave.html",
        {
            "form": form,
            "employee": employee,
            "balances": balances,
            "current_year": current_year,
        },
    )


@login_required
def my_leave_requests_view(request):
    employee = get_object_or_404(
        empProfile,
        user=request.user,
    )

    leave_requests = (
        LeaveRequest.objects
        .filter(employee=employee)
        .select_related(
            "leave_type",
            "reviewed_by",
        )
        .order_by("-created_at")
    )

    current_year = timezone.localdate().year

    balances = (
        LeaveBalance.objects
        .filter(employee=employee, year=current_year)
        .select_related("leave_type")
        .order_by("leave_type__name")
    )

    return render(
        request,
        "appEmp/my_leave_requests.html",
        {
            "employee": employee,
            "leave_requests": leave_requests,
            "balances": balances,
            "current_year": current_year,
        },
    )

@login_required
def pending_leave_requests_view(request):
    logged_in_profile = get_object_or_404(
        empProfile,
        user=request.user,
    )

    if logged_in_profile.role in ADMIN_ROLES:
        leave_requests = LeaveRequest.objects.filter(
            status="PENDING"
        )
    else:
        leave_requests = LeaveRequest.objects.filter(
            status="PENDING",
            employee__manager=logged_in_profile,
        )

    leave_requests = leave_requests.select_related(
        "employee__user",
        "employee__manager__user",
        "leave_type",
    ).order_by("start_date", "created_at")

    return render(
        request,
        "appEmp/pending_leave_requests.html",
        {
            "leave_requests": leave_requests,
        },
    )

@login_required
def review_leave_request_view(request, uuid):
    reviewer_profile = get_object_or_404(
        empProfile,
        user=request.user,
    )

    leave_request = get_object_or_404(
        LeaveRequest.objects.select_related(
            "employee__user",
            "employee__manager__user",
            "leave_type",
        ),
        uuid=uuid,
    )

    is_admin = reviewer_profile.role in ADMIN_ROLES
    is_direct_manager = (
        leave_request.employee.manager_id == reviewer_profile.id
    )

    if not is_admin and not is_direct_manager:
        messages.error(
            request,
            "You don't have permission to review this leave request."
        )
        return redirect("dashboard")

    if leave_request.status != "PENDING":
        messages.info(
            request,
            "This leave request has already been reviewed."
        )
        return redirect("pendingLeaveRequests")

    if request.method == "POST":
        form = LeaveRequestReviewForm(
            request.POST,
            instance=leave_request,
        )

        if form.is_valid():
            action = form.cleaned_data["action"]
            manager_comment = form.cleaned_data.get(
                "manager_comment"
            )

            try:
                with transaction.atomic():
                    locked_request = (
                        LeaveRequest.objects
                        .select_for_update()
                        .select_related(
                            "employee",
                            "leave_type",
                        )
                        .get(pk=leave_request.pk)
                    )

                    if locked_request.status != "PENDING":
                        messages.info(
                            request,
                            "This request was already reviewed."
                        )
                        return redirect("pendingLeaveRequests")

                    if action == "APPROVE":
                        leave_balance = (
                            LeaveBalance.objects
                            .select_for_update()
                            .filter(
                                employee=locked_request.employee,
                                leave_type=locked_request.leave_type,
                                year=locked_request.start_date.year,
                            )
                            .first()
                        )

                        if not leave_balance:
                            messages.error(
                                request,
                                (
                                    "No leave balance exists for this "
                                    "employee, leave type and year."
                                )
                            )
                            return redirect(
                                "reviewLeaveRequest",
                                uuid=locked_request.uuid,
                            )

                        if (
                            leave_balance.available_balance
                            < locked_request.number_of_days
                        ):
                            messages.error(
                                request,
                                (
                                    "Insufficient leave balance. "
                                    f"Available: "
                                    f"{leave_balance.available_balance}, "
                                    f"Requested: "
                                    f"{locked_request.number_of_days}."
                                )
                            )
                            return redirect(
                                "reviewLeaveRequest",
                                uuid=locked_request.uuid,
                            )

                        # Build every calendar date included in the request.
                        leave_dates = []
                        current_date = locked_request.start_date

                        while current_date <= locked_request.end_date:
                            leave_dates.append(current_date)
                            current_date += timedelta(days=1)

                        # Lock any existing attendance records for these dates.
                        existing_attendance = {
                            attendance.date: attendance
                            for attendance in (
                                Attendance.objects
                                .select_for_update()
                                .filter(
                                    employee=locked_request.employee,
                                    date__in=leave_dates,
                                )
                            )
                        }

                        # Do not overwrite a day where the employee has
                        # already checked in or was marked present/late.
                        conflicting_dates = []

                        for leave_date in leave_dates:
                            attendance = existing_attendance.get(
                                leave_date
                            )

                            if not attendance:
                                continue

                            has_work_record = (
                                attendance.check_in is not None
                                or attendance.check_out is not None
                                or attendance.status in [
                                    "PRESENT",
                                    "LATE",
                                ]
                            )

                            if has_work_record:
                                conflicting_dates.append(leave_date)

                        if conflicting_dates:
                            formatted_dates = ", ".join(
                                leave_date.strftime("%d %b %Y")
                                for leave_date in conflicting_dates
                            )

                            messages.error(
                                request,
                                (
                                    "Leave cannot be approved because "
                                    "attendance is already marked on: "
                                    f"{formatted_dates}."
                                )
                            )

                            return redirect(
                                "reviewLeaveRequest",
                                uuid=locked_request.uuid,
                            )

                        # Deduct balance only after all validations pass.
                        leave_balance.used = (
                            leave_balance.used
                            + locked_request.number_of_days
                        )

                        leave_balance.save(
                            update_fields=[
                                "used",
                                "updated_at",
                            ]
                        )

                        is_half_day = (
                            locked_request.duration_type
                            in ["FIRST_HALF", "SECOND_HALF"]
                        )

                        attendance_status = (
                            "HALF_DAY"
                            if is_half_day
                            else "LEAVE"
                        )

                        # Create or update attendance for each approved date.
                        for leave_date in leave_dates:
                            attendance = existing_attendance.get(
                                leave_date
                            )

                            if attendance:
                                attendance.status = attendance_status
                                attendance.marked_by = request.user

                                attendance.save(
                                    update_fields=[
                                        "status",
                                        "marked_by",
                                        "updated_at",
                                    ]
                                )
                            else:
                                Attendance.objects.create(
                                    employee=locked_request.employee,
                                    date=leave_date,
                                    status=attendance_status,
                                    marked_by=request.user,
                                )

                        locked_request.status = "APPROVED"

                        success_message = (
                            "Leave request approved successfully. "
                            "The leave balance and attendance calendar "
                            "have been updated."
                        )

                    else:
                        locked_request.status = "REJECTED"

                        success_message = (
                            "Leave request rejected successfully."
                        )

                    locked_request.reviewed_by = request.user
                    locked_request.reviewed_at = timezone.now()
                    locked_request.manager_comment = manager_comment

                    locked_request.save(
                        update_fields=[
                            "status",
                            "reviewed_by",
                            "reviewed_at",
                            "manager_comment",
                            "updated_at",
                        ]
                    )

                messages.success(
                    request,
                    success_message,
                )

                return redirect("pendingLeaveRequests")

            except LeaveRequest.DoesNotExist:
                messages.error(
                    request,
                    "Leave request could not be found."
                )
                return redirect("pendingLeaveRequests")

    else:
        form = LeaveRequestReviewForm(
            instance=leave_request
        )

    leave_balance = LeaveBalance.objects.filter(
        employee=leave_request.employee,
        leave_type=leave_request.leave_type,
        year=leave_request.start_date.year,
    ).first()

    return render(
        request,
        "appEmp/review_leave_request.html",
        {
            "leave_request": leave_request,
            "leave_balance": leave_balance,
            "form": form,
        },
    )

@login_required
def all_leave_requests_view(request):
    logged_in_profile = get_object_or_404(
        empProfile,
        user=request.user,
    )

    # HR/Admin only
    if logged_in_profile.role not in ADMIN_ROLES:
        messages.error(
            request,
            "You don't have permission to view all leave requests."
        )
        return redirect("dashboard")

    leave_requests = (
        LeaveRequest.objects
        .select_related(
            "employee__user",
            "employee__manager__user",
            "leave_type",
            "reviewed_by",
        )
        .all()
    )

    # ── Filters ─────────────────────────────────────────────

    employee_id = request.GET.get("employee")
    leave_type_id = request.GET.get("leave_type")
    status = request.GET.get("status")
    year = request.GET.get("year")

    if employee_id:
        leave_requests = leave_requests.filter(
            employee_id=employee_id
        )

    if leave_type_id:
        leave_requests = leave_requests.filter(
            leave_type_id=leave_type_id
        )

    if status:
        leave_requests = leave_requests.filter(
            status=status
        )

    if year:
        try:
            year = int(year)

            leave_requests = leave_requests.filter(
                start_date__year=year
            )
        except (TypeError, ValueError):
            year = None

    leave_requests = leave_requests.order_by(
        "-created_at"
    )

    employees = (
        empProfile.objects
        .filter(is_active=True)
        .select_related("user")
        .order_by(
            "user__first_name",
            "user__last_name"
        )
    )

    leave_types = (
        LeaveTypeMaster.objects
        .filter(is_active=True)
        .order_by("name")
    )

    current_year = timezone.localdate().year

    years = range(
        current_year + 1,
        current_year - 5,
        -1
    )

    context = {
        "leave_requests": leave_requests,
        "employees": employees,
        "leave_types": leave_types,
        "years": years,

        # Keep selected filters after submit
        "selected_employee": employee_id,
        "selected_leave_type": leave_type_id,
        "selected_status": status,
        "selected_year": str(year) if year else "",
    }

    return render(
        request,
        "appEmp/all_leave_requests.html",
        context,
    )

@login_required
def leave_balance_list_view(request):
    logged_in_profile = get_object_or_404(
        empProfile,
        user=request.user,
    )

    if logged_in_profile.role not in ADMIN_ROLES:
        messages.error(
            request,
            "You don't have permission to manage leave balances."
        )
        return redirect("dashboard")

    balances = (
        LeaveBalance.objects
        .select_related(
            "employee__user",
            "leave_type",
            "assigned_by",
        )
        .all()
    )

    employee_id = request.GET.get("employee")
    leave_type_id = request.GET.get("leave_type")
    year = request.GET.get("year")

    if employee_id:
        balances = balances.filter(employee_id=employee_id)

    if leave_type_id:
        balances = balances.filter(leave_type_id=leave_type_id)

    if year:
        try:
            balances = balances.filter(year=int(year))
        except (TypeError, ValueError):
            pass

    balances = balances.order_by(
        "-year",
        "employee__user__first_name",
        "leave_type__name",
    )

    employees = (
        empProfile.objects
        .filter(is_active=True)
        .select_related("user")
        .order_by("user__first_name", "user__last_name")
    )

    leave_types = (
        LeaveTypeMaster.objects
        .filter(is_active=True)
        .order_by("name")
    )

    current_year = timezone.localdate().year

    return render(
        request,
        "appEmp/leave_balance_list.html",
        {
            "balances": balances,
            "employees": employees,
            "leave_types": leave_types,
            "years": range(current_year + 1, current_year - 5, -1),
            "selected_employee": employee_id,
            "selected_leave_type": leave_type_id,
            "selected_year": year or "",
        },
    )


@login_required
def leave_balance_edit_view(request, uuid=None):
    logged_in_profile = get_object_or_404(
        empProfile,
        user=request.user,
    )

    if logged_in_profile.role not in ADMIN_ROLES:
        messages.error(
            request,
            "You don't have permission to manage leave balances."
        )
        return redirect("dashboard")

    balance = None

    if uuid:
        balance = get_object_or_404(
            LeaveBalance,
            uuid=uuid,
        )

    if request.method == "POST":
        form = LeaveBalanceForm(
            request.POST,
            instance=balance,
        )

        if form.is_valid():
            record = form.save(commit=False)

            if not record.assigned_by:
                record.assigned_by = request.user

            record.save()

            messages.success(
                request,
                "Leave balance saved successfully."
            )

            return redirect("leaveBalanceList")
    else:
        form = LeaveBalanceForm(instance=balance)

    return render(
        request,
        "appEmp/leave_balance_form.html",
        {
            "form": form,
            "balance": balance,
        },
    )

@login_required
def pending_attendance_exceptions_view(request):
    reviewer_profile = get_object_or_404(
        empProfile,
        user=request.user,
    )

    if reviewer_profile.role in ADMIN_ROLES:
        exception_requests = AttendanceException.objects.filter(
            status="PENDING"
        )
    else:
        exception_requests = AttendanceException.objects.filter(
            status="PENDING",
            attendance__employee__manager=reviewer_profile,
        )

    exception_requests = (
        exception_requests
        .select_related(
            "attendance",
            "attendance__employee__user",
            "attendance__employee__manager__user",
            "raised_by",
        )
        .order_by("attendance__date", "created_at")
    )

    return render(
        request,
        "appEmp/pending_attendance_exceptions.html",
        {
            "exception_requests": exception_requests,
        },
    )

@login_required
def review_attendance_exception_view(request, uuid):
    reviewer_profile = get_object_or_404(
        empProfile,
        user=request.user,
    )

    exception_request = get_object_or_404(
        AttendanceException.objects.select_related(
            "attendance",
            "attendance__employee__user",
            "attendance__employee__manager__user",
            "raised_by",
        ),
        uuid=uuid,
    )

    employee = exception_request.attendance.employee

    is_admin = reviewer_profile.role in ADMIN_ROLES
    is_direct_manager = (
        employee.manager_id == reviewer_profile.id
    )

    if not is_admin and not is_direct_manager:
        messages.error(
            request,
            "You don't have permission to review this attendance exception."
        )
        return redirect("dashboard")

    if exception_request.status != "PENDING":
        messages.info(
            request,
            "This attendance exception has already been reviewed."
        )
        return redirect("pendingAttendanceExceptions")

    if request.method == "POST":
        form = AttendanceExceptionReviewForm(
            request.POST
        )

        if form.is_valid():
            action = form.cleaned_data["action"]
            manager_comment = form.cleaned_data.get(
                "manager_comment"
            )

            try:
                with transaction.atomic():

                    locked_exception = (
                        AttendanceException.objects
                        .select_for_update()
                        .select_related(
                            "attendance",
                            "attendance__employee",
                        )
                        .get(pk=exception_request.pk)
                    )

                    if locked_exception.status != "PENDING":
                        messages.info(
                            request,
                            "This attendance exception was already reviewed."
                        )
                        return redirect(
                            "pendingAttendanceExceptions"
                        )

                    attendance = (
                        Attendance.objects
                        .select_for_update()
                        .get(
                            pk=locked_exception.attendance_id
                        )
                    )

                    if action == "APPROVE":

                        # Exception was created specifically
                        # against an ABSENT attendance record.
                        if attendance.status != "ABSENT":
                            messages.error(
                                request,
                                (
                                    "This attendance record is no longer "
                                    "marked Absent, so the exception cannot "
                                    "be approved automatically."
                                )
                            )

                            return redirect(
                                "reviewAttendanceException",
                                uuid=locked_exception.uuid,
                            )

                        attendance.status = "PRESENT"
                        attendance.marked_by = request.user

                        attendance.save(
                            update_fields=[
                                "status",
                                "marked_by",
                                "updated_at",
                            ]
                        )

                        locked_exception.status = "APPROVED"

                        success_message = (
                            "Attendance exception approved successfully. "
                            "Attendance has been marked Present."
                        )

                    else:
                        locked_exception.status = "REJECTED"

                        success_message = (
                            "Attendance exception rejected successfully."
                        )

                    locked_exception.reviewed_by = request.user
                    locked_exception.reviewed_at = timezone.now()
                    locked_exception.manager_comment = manager_comment

                    locked_exception.save(
                        update_fields=[
                            "status",
                            "reviewed_by",
                            "reviewed_at",
                            "manager_comment",
                            "updated_at",
                        ]
                    )

                messages.success(
                    request,
                    success_message,
                )

                return redirect(
                    "pendingAttendanceExceptions"
                )

            except AttendanceException.DoesNotExist:
                messages.error(
                    request,
                    "Attendance exception could not be found."
                )

                return redirect(
                    "pendingAttendanceExceptions"
                )

    else:
        form = AttendanceExceptionReviewForm()

    return render(
        request,
        "appEmp/review_attendance_exception.html",
        {
            "exception_request": exception_request,
            "attendance": exception_request.attendance,
            "form": form,
        },
    )
