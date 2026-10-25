CORE = "core"  # always on, never stored

# key -> label, the modules it needs, and what it owns.
#   url_names:    URL names that belong to the module (appEmp)
#   view_modules: Python packages whose views all belong to the module (Projects)
MODULES = {
    "attendance": {
        "label": "Attendance", "requires": [],
        "url_names": [
            "checkinCheckout", "editAttendance", "attendanceLocation",
            "attendanceCalendarSelf", "attendanceCalendarAdmin",
            "raiseAttendanceException", "pendingAttendanceExceptions",
            "reviewAttendanceException",
            "workScheduleList", "addWorkSchedule", "editWorkSchedule",
        ],
    },
    "holidays": {
        "label": "Holidays", "requires": [],
        "url_names": [
            "holidayList", "addHoliday", "editHoliday", "holidayCalendar",
            "holidayYear", "holidayBulkUpload", "optionalHolidayApply",
            "pendingOptionalHolidayRequests", "reviewOptionalHolidayRequest",
        ],
    },
    "leave": {
        "label": "Leave", "requires": ["holidays"],
        "url_names": [
            "applyLeave", "myLeaveRequests", "pendingLeaveRequests",
            "allLeaveRequests", "reviewLeaveRequest", "leaveBalanceList",
            "addLeaveBalance",
        ],
    },
    "exit_clearance": {
        "label": "Exit & clearance", "requires": [],
        "url_names": [
            "submitResignation", "myResignations", "pendingResignations",
            "reviewResignation", "managerClearanceQueue",
            "managerClearanceReview", "financeClearanceQueue",
            "financeClearanceReview", "readyForFinalization",
            "finalizeEmployeeExit", "initiateTermination", "allExitRequests",
        ],
    },
    "documents": {
        "label": "Documents", "requires": [],
        "url_names": [
            "upload_document", "hr_document_list", "hr_verify_document",
            "hr_reject_document", "profile_document_upload",
        ],
    },
    "bcas": {
        "label": "BCAS passes", "requires": ["documents"],
        "url_names": [
            "bcasPassDashboard", "bcasPassIssue", "bcasPassStatusUpdate",
            "bcasPassExport",
        ],
    },
    "payroll": {
        "label": "Payroll", "requires": ["attendance"],
        "url_names": [
            "salaryUpdate", "salarySlipSelf", "salarySlipAdmin",
            "salaryCtcPreview", "statutoryProfileUpdate",
            "wageRegisterBulk",
            "payroll", "payrollCycle", "payrollEmployee",
            "payrollPayslip", "payrollSummaryPdf", "payrollBankFile", "payrollEcr",
            "myPayslips", "myPayslipPdf",
        ],
    },
    "projects": {
        "label": "Projects", "requires": [],
        "view_modules": ["app_projects"],
    },
    "bulk_import": {
        "label": "Employee bulk import", "requires": [],
        "url_names": ["employeeBulkImport"],
    },
    "whatsapp": {
        "label": "WhatsApp", "requires": [],
        "url_names": ["whatsapp_webhook"],
    },
}

# URL names that are always available. The coverage test fails if a URL is
# in neither this set nor a module, so a new page cannot be forgotten.
CORE_URL_NAMES = {
    "dashboard", "employeeList", "employeeListPdf", "myProfile", "editProfile",
    "register", "verificationStats", "verificationQuickUpdate",
    "create_organization", "switch_organization",
    "home", "demo_request", "login", "logout", "verify_otp", "contact_us",
}

URL_NAME_TO_MODULE = {
    name: key
    for key, meta in MODULES.items()
    for name in meta.get("url_names", [])
}


def effective_modules(direct_keys):
    """Directly bought modules plus everything they require, transitively."""
    result = set()
    stack = list(direct_keys)
    while stack:
        key = stack.pop()
        if key in result or key not in MODULES:
            continue
        result.add(key)
        stack.extend(MODULES[key]["requires"])
    return result


def module_for_view(view_func, url_name=None):
    """Which module a view belongs to, or None if it is core / not gated."""
    if url_name in URL_NAME_TO_MODULE:
        return URL_NAME_TO_MODULE[url_name]
    path = getattr(view_func, "__module__", "") or ""
    for key, meta in MODULES.items():
        for prefix in meta.get("view_modules", []):
            if path == prefix or path.startswith(prefix + "."):
                return key
    return None