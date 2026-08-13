from .models import (
    ClearanceApproval,
    empProfile,
)


def user_role(request):
    if not request.user.is_authenticated:
        return {
            "is_admin_role": False,
            "is_manager_role": False,

            "has_employee_profile": False,

            "can_view_hr_dashboard": False,
            "can_manage_employees": False,
            "can_manage_attendance": False,
            "can_review_leave": False,
            "can_manage_leave_balance": False,
            "can_review_attendance_exception": False,
            "can_manage_salary": False,

            # Exit / Clearance
            "can_review_manager_noc": False,
            "can_review_finance_noc": False,
            "can_view_all_clearance_requests": False,
            "can_apply_clearance_for_employee": False,
            "can_initiate_employee_exit": False,
            "can_finalize_employee_exit": False,
        }

    user = request.user

    # ---------------------------------------------------------
    # Existing HRMS permissions
    # ---------------------------------------------------------

    can_view_hr_dashboard = (
        user.is_superuser
        or user.has_perm("appEmp.view_hr_dashboard")
    )

    can_manage_employees = (
        user.is_superuser
        or user.has_perm("appEmp.manage_employees")
    )

    can_manage_attendance = (
        user.is_superuser
        or user.has_perm("appEmp.manage_attendance")
    )

    can_review_leave = (
        user.is_superuser
        or user.has_perm("appEmp.review_leave")
    )

    can_manage_leave_balance = (
        user.is_superuser
        or user.has_perm("appEmp.manage_leave_balance")
    )

    can_review_attendance_exception = (
        user.is_superuser
        or user.has_perm(
            "appEmp.review_attendance_exception"
        )
    )

    can_manage_salary = (
        user.is_superuser
        or user.has_perm("appEmp.manage_salary")
    )

    # ---------------------------------------------------------
    # Employee profile
    # ---------------------------------------------------------

    has_employee_profile = empProfile.objects.filter(
        user=user,
        is_active=True,
    ).exists()

    # ---------------------------------------------------------
    # Manager Clearance access
    #
    # Manager NOC is object-level:
    # - user has employees reporting to them, OR
    # - a pending Manager NOC is directly assigned to them
    #
    # Superuser can also see the menu.
    # ---------------------------------------------------------

    has_direct_reports = empProfile.objects.filter(
        manager__user=user,
        is_active=True,
    ).exists()

    has_pending_manager_noc = (
        ClearanceApproval.objects.filter(
            approval_type="MANAGER_NOC",
            assigned_to=user,
            status="PENDING",
            clearance_request__status="PENDING",
        ).exists()
    )

    can_review_manager_noc = (
        user.is_superuser
        or has_direct_reports
        or has_pending_manager_noc
    )

    # ---------------------------------------------------------
    # Finance Clearance
    # ---------------------------------------------------------

    can_review_finance_noc = (
        user.is_superuser
        or user.has_perm(
            "appEmp.review_finance_noc"
        )
    )

    # ---------------------------------------------------------
    # HR Exit / Clearance permissions
    # ---------------------------------------------------------

    can_view_all_clearance_requests = (
        user.is_superuser
        or user.has_perm(
            "appEmp.view_all_clearance_requests"
        )
    )

    can_apply_clearance_for_employee = (
        user.is_superuser
        or user.has_perm(
            "appEmp.apply_clearance_for_employee"
        )
    )

    can_initiate_employee_exit = (
        user.is_superuser
        or user.has_perm(
            "appEmp.initiate_employee_exit"
        )
    )

    can_finalize_employee_exit = (
        user.is_superuser
        or user.has_perm(
            "appEmp.finalize_employee_exit"
        )
    )

    # ---------------------------------------------------------
    # Context
    # ---------------------------------------------------------

    return {
        "is_admin_role": can_view_hr_dashboard,

        "is_manager_role": (
            can_review_leave
            or can_review_attendance_exception
            or can_review_manager_noc
        ),

        "has_employee_profile": has_employee_profile,

        "can_view_hr_dashboard": can_view_hr_dashboard,
        "can_manage_employees": can_manage_employees,
        "can_manage_attendance": can_manage_attendance,
        "can_review_leave": can_review_leave,
        "can_manage_leave_balance": can_manage_leave_balance,
        "can_review_attendance_exception": (
            can_review_attendance_exception
        ),
        "can_manage_salary": can_manage_salary,

        # Exit / Clearance
        "can_review_manager_noc": can_review_manager_noc,
        "can_review_finance_noc": can_review_finance_noc,
        "can_view_all_clearance_requests": (
            can_view_all_clearance_requests
        ),
        "can_apply_clearance_for_employee": (
            can_apply_clearance_for_employee
        ),
        "can_initiate_employee_exit": (
            can_initiate_employee_exit
        ),
        "can_finalize_employee_exit": (
            can_finalize_employee_exit
        ),
    }