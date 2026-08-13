from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    ClearanceApproval,
    ClearanceRequest,
    EmployeeExitRequest,
)


ACTIVE_EXIT_STATUSES = [
    "SUBMITTED",
    "CLEARANCE_IN_PROGRESS",
    "READY_FOR_FINALIZATION",
]


@transaction.atomic
def create_clearance_request(
    *,
    employee,
    requested_by,
    request_type="NOC",
    reason,
):
    """
    Create one overall clearance request and its initial
    Manager NOC + Finance NOC approval steps.

    Permission checks are handled by the calling view.
    """

    valid_request_types = {
        "NOC",
        "TERMINATION",
    }

    if request_type not in valid_request_types:
        raise ValidationError(
            "Invalid clearance request type."
        )

    if not employee.is_active:
        raise ValidationError(
            "Clearance cannot be created for an inactive employee."
        )

    if not employee.manager:
        raise ValidationError(
            "This employee does not have a reporting manager assigned."
        )

    if not (reason or "").strip():
        raise ValidationError(
            "A reason is required for the clearance request."
        )

    clearance_request = ClearanceRequest.objects.create(
        employee=employee,
        request_type=request_type,
        requested_by=requested_by,
        reason=reason.strip(),
        status="PENDING",
    )

    # Manager / Site NOC
    ClearanceApproval.objects.create(
        clearance_request=clearance_request,
        approval_type="MANAGER_NOC",
        assigned_to=employee.manager.user,
        status="PENDING",
    )

    # Shared Finance queue
    ClearanceApproval.objects.create(
        clearance_request=clearance_request,
        approval_type="FINANCE_NOC",
        assigned_to=None,
        status="PENDING",
    )

    return clearance_request


def sync_exit_status_from_clearance(clearance_request):
    """
    Keep EmployeeExitRequest status synchronized with
    its linked internal clearance workflow.
    """

    try:
        exit_request = clearance_request.employee_exit_request

    except EmployeeExitRequest.DoesNotExist:
        # Standalone clearance request, not related to an exit.
        return None

    # Never reopen an already closed exit.
    if exit_request.status in [
        "COMPLETED",
        "HR_REJECTED",
    ]:
        return exit_request

    if clearance_request.status == "REJECTED":
        new_status = "CLEARANCE_REJECTED"

    elif clearance_request.status in [
        "COMPLETED",
        "READY_FOR_FINALIZATION",
    ]:
        new_status = "READY_FOR_FINALIZATION"

    else:
        new_status = "CLEARANCE_IN_PROGRESS"

    if exit_request.status != new_status:
        exit_request.status = new_status

        exit_request.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

    return exit_request


def update_clearance_request_status(clearance_request):
    """
    Recalculate the overall ClearanceRequest status
    based on its Manager and Finance approval steps.
    """

    approvals = list(
        clearance_request.approvals.all()
    )

    # Any rejection closes the clearance.
    if any(
        approval.status == "REJECTED"
        for approval in approvals
    ):
        clearance_request.status = "REJECTED"

        clearance_request.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

        sync_exit_status_from_clearance(
            clearance_request
        )

        return clearance_request

    # Still waiting for one or more approvals.
    if not approvals or any(
        approval.status != "APPROVED"
        for approval in approvals
    ):
        clearance_request.status = "PENDING"

        clearance_request.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

        sync_exit_status_from_clearance(
            clearance_request
        )

        return clearance_request

    # All approvals approved.
    if clearance_request.request_type == "TERMINATION":
        clearance_request.status = "READY_FOR_FINALIZATION"

        clearance_request.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

    else:
        clearance_request.status = "COMPLETED"
        clearance_request.completed_at = timezone.now()

        clearance_request.save(
            update_fields=[
                "status",
                "completed_at",
                "updated_at",
            ]
        )

    sync_exit_status_from_clearance(
        clearance_request
    )

    return clearance_request


@transaction.atomic
def decide_clearance_approval(
    *,
    approval,
    decided_by,
    decision,
    remarks="",
):
    """
    Approve or reject one clearance approval.

    Permission / ownership checks are handled
    by the calling view.
    """

    valid_decisions = {
        "APPROVED",
        "REJECTED",
    }

    if decision not in valid_decisions:
        raise ValidationError(
            "Invalid clearance approval decision."
        )

    if approval.status != "PENDING":
        raise ValidationError(
            "This clearance approval has already been decided."
        )

    clearance_request = approval.clearance_request

    if clearance_request.status != "PENDING":
        raise ValidationError(
            "This clearance request is no longer pending."
        )

    cleaned_remarks = (remarks or "").strip()

    if (
        decision == "REJECTED"
        and not cleaned_remarks
    ):
        raise ValidationError(
            "Remarks are required when rejecting a clearance request."
        )

    approval.status = decision
    approval.decided_by = decided_by
    approval.decided_at = timezone.now()
    approval.remarks = cleaned_remarks or None

    approval.save(
        update_fields=[
            "status",
            "decided_by",
            "decided_at",
            "remarks",
            "updated_at",
        ]
    )

    update_clearance_request_status(
        clearance_request
    )

    clearance_request.refresh_from_db()

    return approval


@transaction.atomic
def submit_resignation(
    *,
    employee,
    initiated_by,
    reason,
    proposed_last_working_date,
):
    """
    Employee submits a resignation.

    IMPORTANT:
    No Manager / Finance NOC is created at this stage.
    Clearance begins only after HR accepts the resignation.
    """

    if not employee.is_active:
        raise ValidationError(
            "An inactive employee cannot submit a resignation."
        )

    if not (reason or "").strip():
        raise ValidationError(
            "A resignation reason is required."
        )

    if not proposed_last_working_date:
        raise ValidationError(
            "Proposed last working date is required."
        )

    existing_exit = EmployeeExitRequest.objects.filter(
        employee=employee,
        status__in=ACTIVE_EXIT_STATUSES,
    ).exists()

    if existing_exit:
        raise ValidationError(
            "An active resignation or exit request already exists "
            "for this employee."
        )

    exit_request = EmployeeExitRequest.objects.create(
        employee=employee,
        exit_type="RESIGNATION",
        initiated_by=initiated_by,
        reason=reason.strip(),
        proposed_last_working_date=proposed_last_working_date,
        status="SUBMITTED",
    )

    return exit_request


@transaction.atomic
def review_resignation(
    *,
    exit_request,
    reviewed_by,
    decision,
    remarks="",
    final_last_working_date=None,
):
    """
    HR approves or rejects an employee resignation.

    Approval automatically starts Manager + Finance clearance.
    """

    if exit_request.exit_type != "RESIGNATION":
        raise ValidationError(
            "Only resignation requests can be reviewed here."
        )

    if exit_request.status != "SUBMITTED":
        raise ValidationError(
            "This resignation has already been reviewed."
        )

    valid_decisions = {
        "APPROVED",
        "REJECTED",
    }

    if decision not in valid_decisions:
        raise ValidationError(
            "Invalid resignation review decision."
        )

    cleaned_remarks = (remarks or "").strip()

    if (
        decision == "REJECTED"
        and not cleaned_remarks
    ):
        raise ValidationError(
            "HR remarks are required when rejecting a resignation."
        )

    # ---------------------------------------------------------
    # HR rejects resignation
    # ---------------------------------------------------------
    if decision == "REJECTED":
        exit_request.status = "HR_REJECTED"
        exit_request.hr_reviewed_by = reviewed_by
        exit_request.hr_reviewed_at = timezone.now()
        exit_request.hr_remarks = cleaned_remarks or None

        exit_request.save(
            update_fields=[
                "status",
                "hr_reviewed_by",
                "hr_reviewed_at",
                "hr_remarks",
                "updated_at",
            ]
        )

        return exit_request

    # ---------------------------------------------------------
    # HR accepts resignation
    # ---------------------------------------------------------
    approved_last_working_date = (
        final_last_working_date
        or exit_request.proposed_last_working_date
    )

    clearance_request = create_clearance_request(
        employee=exit_request.employee,
        requested_by=reviewed_by,
        request_type="NOC",
        reason=(
            "Exit clearance for accepted resignation. "
            f"Reason: {exit_request.reason}"
        ),
    )

    exit_request.status = "CLEARANCE_IN_PROGRESS"
    exit_request.hr_reviewed_by = reviewed_by
    exit_request.hr_reviewed_at = timezone.now()
    exit_request.hr_remarks = cleaned_remarks or None
    exit_request.final_last_working_date = (
        approved_last_working_date
    )
    exit_request.clearance_request = clearance_request

    exit_request.save(
        update_fields=[
            "status",
            "hr_reviewed_by",
            "hr_reviewed_at",
            "hr_remarks",
            "final_last_working_date",
            "clearance_request",
            "updated_at",
        ]
    )

    return exit_request


@transaction.atomic
def initiate_termination(
    *,
    employee,
    initiated_by,
    reason,
    final_last_working_date=None,
):
    """
    HR initiates employee termination.

    Unlike resignation, no separate HR acceptance step is needed.
    Manager + Finance clearance starts immediately.
    """

    if not employee.is_active:
        raise ValidationError(
            "This employee is already inactive."
        )

    if not (reason or "").strip():
        raise ValidationError(
            "A termination reason is required."
        )

    existing_exit = EmployeeExitRequest.objects.filter(
        employee=employee,
        status__in=ACTIVE_EXIT_STATUSES,
    ).exists()

    if existing_exit:
        raise ValidationError(
            "An active resignation or exit request already exists "
            "for this employee."
        )

    exit_request = EmployeeExitRequest.objects.create(
        employee=employee,
        exit_type="TERMINATION",
        initiated_by=initiated_by,
        reason=reason.strip(),
        final_last_working_date=final_last_working_date,
        status="CLEARANCE_IN_PROGRESS",
        hr_reviewed_by=initiated_by,
        hr_reviewed_at=timezone.now(),
    )

    clearance_request = create_clearance_request(
        employee=employee,
        requested_by=initiated_by,
        request_type="TERMINATION",
        reason=(
            "Exit clearance for HR-initiated termination. "
            f"Reason: {reason.strip()}"
        ),
    )

    exit_request.clearance_request = clearance_request

    exit_request.save(
        update_fields=[
            "clearance_request",
            "updated_at",
        ]
    )

    return exit_request

@transaction.atomic
def finalize_employee_exit(
    *,
    exit_request,
    finalized_by,
):
    """
    Finalize an employee resignation or termination after
    all required clearances have been approved.

    Finalization:
    - can happen only when exit is READY_FOR_FINALIZATION
    - cannot happen before the final last working date
    - marks the exit COMPLETED
    - deactivates employee profile
    - deactivates Django user login
    - stores finalization audit details
    """

    if exit_request.status != "READY_FOR_FINALIZATION":
        raise ValidationError(
            "This employee exit is not ready for finalization."
        )

    if not exit_request.final_last_working_date:
        raise ValidationError(
            "Final last working date must be set before finalizing the exit."
        )

    today = timezone.localdate()

    if exit_request.final_last_working_date > today:
        raise ValidationError(
            (
                "This employee cannot be finalized before their "
                f"last working date "
                f"({exit_request.final_last_working_date})."
            )
        )

    employee = exit_request.employee
    user = employee.user

    now = timezone.now()

    # ---------------------------------------------------------
    # Complete Employee Exit
    # ---------------------------------------------------------

    exit_request.status = "COMPLETED"
    exit_request.finalized_by = finalized_by
    exit_request.finalized_at = now

    exit_request.save(
        update_fields=[
            "status",
            "finalized_by",
            "finalized_at",
            "updated_at",
        ]
    )

    # ---------------------------------------------------------
    # Complete linked clearance audit
    # ---------------------------------------------------------

    if exit_request.clearance_request_id:
        clearance_request = exit_request.clearance_request

        clearance_request.status = "COMPLETED"
        clearance_request.finalized_by = finalized_by
        clearance_request.finalized_at = now

        if not clearance_request.completed_at:
            clearance_request.completed_at = now

        clearance_request.save(
            update_fields=[
                "status",
                "completed_at",
                "finalized_by",
                "finalized_at",
                "updated_at",
            ]
        )

    # ---------------------------------------------------------
    # Deactivate employee profile
    # ---------------------------------------------------------

    if employee.is_active:
        employee.is_active = False

        employee.save(
            update_fields=[
                "is_active",
            ]
        )

    # ---------------------------------------------------------
    # Disable employee login
    # ---------------------------------------------------------

    if user.is_active:
        user.is_active = False

        user.save(
            update_fields=[
                "is_active",
            ]
        )

    return exit_request

