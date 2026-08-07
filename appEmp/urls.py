
# from . import views
# from django.urls import path
# from .views import (
#     empProfile_view,
#     empList_view,
#     profileDetail_view,
#     dashboard_view,
#     checkin_checkout_view,
#     update_attendance_view,
#     salary_update_view,
#     salary_slip_self_view,
#     salary_slip_admin_view,
#     attendance_calendar_self_view,
#     attendance_calendar_admin_view,raise_attendance_exception_view
# )

# urlpatterns = [
#     path("profile/<uuid:uuid>/", profileDetail_view, name="editProfile"),
#     path('empProfile', empProfile_view, name='myProfile'),
#     path('empList/', empList_view, name='employeeList'),
#     path('dashboard/', dashboard_view, name='dashboard'),
#     path('attendance/checkin-checkout/', checkin_checkout_view, name='checkinCheckout'),
#     path('attendance/<uuid:uuid>/edit/', update_attendance_view, name='editAttendance'),
#     # ── Add to appEmp/urls.py, inside urlpatterns ────────────────────────────

#     path("attendance/calendar/",attendance_calendar_self_view,name="attendanceCalendarSelf",),

#     path("attendance/calendar/<uuid:uuid>/",attendance_calendar_admin_view,name="attendanceCalendarAdmin",),
#     path(
#     "attendance/<uuid:attendance_uuid>/raise-exception/",
#     raise_attendance_exception_view,
#     name="raiseAttendanceException",
# ),
#     path('salary/save/<uuid:uuid>/', views.salary_update_view, name='salaryUpdate'),
#     path('salary/slip/<int:year>/<int:month>/', views.salary_slip_self_view, name='salarySlipSelf'),
#     path('salary/<uuid:uuid>/slip/<int:year>/<int:month>/', views.salary_slip_admin_view, name='salarySlipAdmin'),
# ] 

from django.urls import path

from . import views
from .views import (
    empProfile_view,
    empList_view,
    profileDetail_view,
    dashboard_view,
    checkin_checkout_view,
    update_attendance_view,
    attendance_calendar_self_view,
    attendance_calendar_admin_view,
    raise_attendance_exception_view,
    apply_leave_view,
    my_leave_requests_view,
    pending_leave_requests_view,
    review_leave_request_view,
    all_leave_requests_view,
    leave_balance_list_view,
    leave_balance_edit_view,
    pending_attendance_exceptions_view, 
    review_attendance_exception_view,
)


urlpatterns = [
    path(
        "profile/<uuid:uuid>/",
        profileDetail_view,
        name="editProfile",
    ),

    path(
        "empProfile",
        empProfile_view,
        name="myProfile",
    ),

    path(
        "empList/",
        empList_view,
        name="employeeList",
    ),

    path(
        "dashboard/",
        dashboard_view,
        name="dashboard",
    ),

    path(
        "attendance/checkin-checkout/",
        checkin_checkout_view,
        name="checkinCheckout",
    ),

    path(
        "attendance/<uuid:uuid>/edit/",
        update_attendance_view,
        name="editAttendance",
    ),

    path(
        "attendance/calendar/",
        attendance_calendar_self_view,
        name="attendanceCalendarSelf",
    ),

    path(
        "attendance/calendar/<uuid:uuid>/",
        attendance_calendar_admin_view,
        name="attendanceCalendarAdmin",
    ),

    path(
        "attendance/<uuid:attendance_uuid>/raise-exception/",
        raise_attendance_exception_view,
        name="raiseAttendanceException",
    ),

    path(
        "leave/apply/",
        apply_leave_view,
        name="applyLeave",
    ),

    path(
        "leave/my-requests/",
        my_leave_requests_view,
        name="myLeaveRequests",
    ),

    path(
        "salary/save/<uuid:uuid>/",
        views.salary_update_view,
        name="salaryUpdate",
    ),

    path(
        "salary/slip/<int:year>/<int:month>/",
        views.salary_slip_self_view,
        name="salarySlipSelf",
    ),

    path(
        "salary/<uuid:uuid>/slip/<int:year>/<int:month>/",
        views.salary_slip_admin_view,
        name="salarySlipAdmin",
    ),
    path(
    "leave/pending/",
    pending_leave_requests_view,
    name="pendingLeaveRequests",
),
path(
    "leave/all/",
    all_leave_requests_view,
    name="allLeaveRequests",
),

path(
    "leave/<uuid:uuid>/review/",
    review_leave_request_view,
    name="reviewLeaveRequest",
),
path(
    "leave/balances/",
    leave_balance_list_view,
    name="leaveBalanceList",
),

path(
    "leave/balances/add/",
    leave_balance_edit_view,
    name="addLeaveBalance",
),

path(
    "leave/balances/<uuid:uuid>/edit/",
    leave_balance_edit_view,
    name="editLeaveBalance",
),
path(
    "attendance/exceptions/pending/",
    pending_attendance_exceptions_view,
    name="pendingAttendanceExceptions",
),

path(
    "attendance/exceptions/<uuid:uuid>/review/",
    review_attendance_exception_view,
    name="reviewAttendanceException",
),
]