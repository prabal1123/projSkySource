from django.contrib import messages
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Count, Q
from .models import empProfile
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required

from .models import empProfile, Attendance, ADMIN_ROLES, LATE_CUTOFF_TIME
from .forms import EmployeeForm, ProfileFormAdmin,AttendanceUpdateForm

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

    return render(
        request,
        "appEmp/profile.html",
        {
            "employee": employee,
            "profile": employee, 
            "form": form,
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
    return render(request, "appEmp/profile.html",
        {"form": form, "profile": profile, "created": created},
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


# @login_required
# def update_attendance_view(request, pk):
#     profile = get_object_or_404(empProfile, user=request.user)
#     if profile.role not in ADMIN_ROLES:
#         messages.error(request, "You don't have permission to do that.")
#         return redirect('dashboard')

#     attendance = get_object_or_404(Attendance, pk=pk)

#     if request.method == "POST":
#         form = AttendanceUpdateForm(request.POST, instance=attendance)
#         if form.is_valid():
#             record = form.save(commit=False)
#             record.marked_by = request.user
#             record.save()
#             messages.success(request, f"Attendance updated for {attendance.employee}.")
#             return redirect('dashboard')
#     else:
#         form = AttendanceUpdateForm(instance=attendance)

#     return render(request, "appEmp/edit_attendance.html", {"form": form, "attendance": attendance})

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
