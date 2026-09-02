
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
        "attendance/<uuid:uuid>/edit/",
        update_attendance_view,
        name="editAttendance",
    ),

    path(
        "attendance/<uuid:uuid>/location/",
        views.attendance_location_view,
        name="attendanceLocation",
    ),
    path(

    "holidays/optional/apply/",
    views.optional_holiday_apply_view,
    name="optionalHolidayApply",
),
path(
    "employees/bulk-import/",
    views.employee_bulk_import_view,
    name="employeeBulkImport",
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
    path('whatsapp/webhook/', views.whatsapp_webhook, name='whatsapp_webhook'),
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
path("documents/", views.upload_document, name="upload_document"),
path("hr/documents/", views.hr_document_list, name="hr_document_list"),
path("hr/documents/<int:doc_id>/verify/", views.hr_verify_document, name="hr_verify_document"),


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

# path(
#     "leave/balances/<uuid:uuid>/edit/",
#     leave_balance_edit_view,
#     name="editLeaveBalance",
# ),
path(
    "attendance/exceptions/pending/",
    pending_attendance_exceptions_view,
    name="pendingAttendanceExceptions",
),

path(
    "holidays/",
    views.holiday_list_view,
    name="holidayList",
),

path(
    "holidays/add/",
    views.holiday_create_view,
    name="addHoliday",
),

path(
    "holidays/<uuid:uuid>/edit/",
    views.holiday_edit_view,
    name="editHoliday",
),
path(
    "holidays/calendar/",
    views.holiday_calendar_view,
    name="holidayCalendar",
),
path(
    "holidays/year/",
    views.holiday_year_view,
    name="holidayYear",
),
path(
    "holidays/bulk-upload/",
    views.holiday_bulk_upload_view,
    name="holidayBulkUpload",
),
path(
    "attendance/exceptions/<uuid:uuid>/review/",
    review_attendance_exception_view,
    name="reviewAttendanceException",
),
path(
    "work-schedules/",
    views.work_schedule_list_view,
    name="workScheduleList",
),

path(
    "work-schedules/add/",
    views.work_schedule_create_view,
    name="addWorkSchedule",
),

path(
    "work-schedules/<uuid:uuid>/edit/",
    views.work_schedule_edit_view,
    name="editWorkSchedule",
),

path(
    "exit/resign/",
    views.submit_resignation_view,
    name="submitResignation",
),
path(
    "exit/my-resignations/",
    views.my_resignations_view,
    name="myResignations",
),
path(
    "exit/hr/pending-resignations/",
    views.pending_resignations_view,
    name="pendingResignations",
),
path(
    "exit/hr/resignation/<uuid:uuid>/review/",
    views.review_resignation_view,
    name="reviewResignation",
),
path(
    "clearance/manager/pending/",
    views.manager_clearance_queue_view,
    name="managerClearanceQueue",
),
path(
    "clearance/manager/<uuid:uuid>/review/",
    views.manager_clearance_review_view,
    name="managerClearanceReview",
),
path(
    "clearance/finance/pending/",
    views.finance_clearance_queue_view,
    name="financeClearanceQueue",
),
path(
    "clearance/finance/<uuid:uuid>/review/",
    views.finance_clearance_review_view,
    name="financeClearanceReview",
),
path(
    "exit/hr/ready-for-finalization/",
    views.ready_for_finalization_view,
    name="readyForFinalization",
),
path(
    "exit/hr/<uuid:uuid>/finalize/",
    views.finalize_employee_exit_view,
    name="finalizeEmployeeExit",
),
path(
    "exit/hr/initiate-termination/",
    views.initiate_termination_view,
    name="initiateTermination",
),
path(
    "exit/hr/all/",
    views.all_exit_requests_view,
    name="allExitRequests",
),
path(
    "holidays/optional/pending/",
    views.pending_optional_holiday_requests_view,
    name="pendingOptionalHolidayRequests",
),

path(
    "holidays/optional/<uuid:uuid>/review/",
    views.review_optional_holiday_request_view,
    name="reviewOptionalHolidayRequest",
),
path("profile/<uuid:uuid>/documents/upload/", views.profile_document_upload, name="profile_document_upload"),
]