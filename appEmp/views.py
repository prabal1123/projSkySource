import calendar
from io import BytesIO

from django.contrib import messages
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.utils import timezone
from django.db.models import Count, Q

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

from .models import empProfile, Attendance, ADMIN_ROLES, LATE_CUTOFF_TIME, Salary
from .forms import EmployeeForm, ProfileFormAdmin, AttendanceUpdateForm, SalaryForm
 
@login_required
def empList_view(request):
    objects = empProfile.objects.values("id","user__first_name", "user__last_name", "phone_number", "uuid")

    return render(request, "appEmp/empList.html", {"objects": objects})

@login_required
def profileDetail_view(request, uuid):
    employee = get_object_or_404(empProfile, uuid=uuid)

    if request.method == "POST":
        form = ProfileFormAdmin(request.POST, instance=employee)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully.")
            return redirect("editProfile", uuid=employee.uuid)
    else:
        form = ProfileFormAdmin(instance=employee)

    target_salary = employee.salary_records.filter(is_active=True).first()

    return render(
        request,
        "appEmp/profile.html",
        {
            "employee": employee,
            "profile": employee,
            "form": form,
            "salary": target_salary,
            "can_edit_salary": True,
            "salary_form": SalaryForm(instance=target_salary),
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
def dashboard_view(request):
    profile = get_object_or_404(empProfile, user=request.user)
    today = timezone.localdate()

    if profile.role in ADMIN_ROLES:
        total_employees = empProfile.objects.count()

        verification_stats = {
            "email": empProfile.objects.filter(is_email_verified=True).count(),
            "phone": empProfile.objects.filter(is_phone_verified=True).count(),
            "address": empProfile.objects.filter(is_address_verified=True).count(),
            "aadhar": empProfile.objects.filter(is_aadhar_verified=True).count(),
            "background_check": empProfile.objects.filter(is_background_check_completed=True).count(),
        }

        today_attendance = Attendance.objects.filter(date=today)
        attendance_summary = {
            "present": today_attendance.filter(status__in=['PRESENT', 'LATE', 'HALF_DAY']).count(),
            "absent": today_attendance.filter(status='ABSENT').count(),
            "leave": today_attendance.filter(status='LEAVE').count(),
            "not_marked": total_employees - today_attendance.count(),
        }

        context = {
            "is_admin_view": True,
            "total_employees": total_employees,
            "verification_stats": verification_stats,
            "attendance_summary": attendance_summary,
            "today_attendance": today_attendance.select_related('employee__user'),
        }
    else:
        my_attendance_today = Attendance.objects.filter(employee=profile, date=today).first()
        recent_attendance = Attendance.objects.filter(employee=profile).order_by('-date')[:7]

        context = {
            "is_admin_view": False,
            "profile": profile,
            "my_attendance_today": my_attendance_today,
            "recent_attendance": recent_attendance,
        }

    return render(request, "dashboard.html", context)


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

