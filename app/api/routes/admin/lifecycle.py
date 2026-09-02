import uuid

from fastapi import APIRouter, status

from app.api.dependencies.staff import StaffAdminDep, StaffOwnerDep
from app.api.errors import (
    ADMIN_FORBIDDEN,
    ADMIN_NOT_FOUND,
    ADMIN_UNAUTHORISED,
    BAD_CONFIRMATION,
    LIFECYCLE_CONFLICT,
    RATE_LIMITED,
)
from app.api.routes.admin.workspaces import summary_of
from app.schemas.admin_console import AdminWorkspaceSummary
from app.schemas.admin_lifecycle import (
    ConfirmSlugRequest,
    EraseAfterRequest,
    SuspendRequest,
)
from app.services.admin_lifecycle_service import AdminLifecycleServiceDep

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["platform"])

PLATFORM = {
    **ADMIN_UNAUTHORISED,
    **ADMIN_FORBIDDEN,
    **RATE_LIMITED,
    **ADMIN_NOT_FOUND,
}
LIFECYCLE = {**PLATFORM, **LIFECYCLE_CONFLICT}
DESTRUCTIVE = {**LIFECYCLE, **BAD_CONFIRMATION}


# `admin` throughout, except the last, which is `owner`. Suspending an
# account is an operational decision somebody has to be able to take at
# two in the morning; destroying one is not, and the rank is the first of
# three things standing in front of it -- the others being the slug in
# the body and the entry written before it runs.
@router.post("/suspend", responses=LIFECYCLE)
def suspend_workspace(
    workspace_id: uuid.UUID,
    payload: SuspendRequest,
    actor: StaffAdminDep,
    service: AdminLifecycleServiceDep,
) -> AdminWorkspaceSummary:
    """Freeze an account: reachable, readable, and unchangeable.

    Not locked out, which is the useful reading and the one the status
    enum's own comment promises. A business that has not paid should be
    able to read its history, see what it owes and settle it — taking
    their records away over an invoice punishes them for the thing you
    want them to fix.

    Their inbox keeps receiving. A suspended workspace still ingests
    inbound messages and simply does not answer them automatically,
    because losing a customer's question over their supplier's unpaid
    bill would be the worst thing a suspension could do.
    """
    return summary_of(service.suspend(actor, workspace_id, reason=payload.reason))


@router.post("/unsuspend", responses=LIFECYCLE)
def unsuspend_workspace(
    workspace_id: uuid.UUID,
    actor: StaffAdminDep,
    service: AdminLifecycleServiceDep,
) -> AdminWorkspaceSummary:
    """Thaw an account.

    A no-op on one that was never frozen, and nothing is recorded for it.
    Refusing would be a confusing answer to somebody trying to put things
    right.
    """
    return summary_of(service.unsuspend(actor, workspace_id))


@router.post("/cancel", responses=DESTRUCTIVE)
def cancel_workspace(
    workspace_id: uuid.UUID,
    payload: ConfirmSlugRequest,
    actor: StaffAdminDep,
    service: AdminLifecycleServiceDep,
) -> AdminWorkspaceSummary:
    """Close an account on the customer's behalf, and start the clock.

    Through the same path a customer's own close takes, so the grace
    period and the erasure job behave identically. Nothing is destroyed
    today: the workspace is marked closed and given a date, and until
    that date `restore` brings it back intact.
    """
    return summary_of(
        service.cancel(actor, workspace_id, confirm_slug=payload.confirm_slug)
    )


@router.post("/restore", responses=LIFECYCLE)
def restore_workspace(
    workspace_id: uuid.UUID,
    actor: StaffAdminDep,
    service: AdminLifecycleServiceDep,
) -> AdminWorkspaceSummary:
    """Bring a closed account back, before its erasure date.

    Refused once that date has passed, rather than pretending. By then
    the erasure job may have run, may be running, or may run in the next
    minute, and "restored" would be a promise this cannot keep.
    """
    return summary_of(service.restore(actor, workspace_id))


@router.patch("/erase-after", responses=LIFECYCLE)
def reschedule_erasure(
    workspace_id: uuid.UUID,
    payload: EraseAfterRequest,
    actor: StaffAdminDep,
    service: AdminLifecycleServiceDep,
) -> AdminWorkspaceSummary:
    """Move the date a closed account's records are destroyed.

    Both directions. Forward is a customer asking to be forgotten sooner;
    back is a dispute or a legal hold. Without this, one of those happens
    in a database console.
    """
    return summary_of(
        service.reschedule_erasure(actor, workspace_id, erase_after=payload.erase_after)
    )


@router.post(
    "/erase-now",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=DESTRUCTIVE,
)
def erase_workspace_now(
    workspace_id: uuid.UUID,
    payload: ConfirmSlugRequest,
    actor: StaffOwnerDep,
    service: AdminLifecycleServiceDep,
) -> None:
    """Destroy a workspace and everything it holds, immediately.

    The most destructive call in the product. Owner rank, the slug typed
    back in the body, and the audit entry written and committed *before*
    the delete rather than after -- because afterwards there is no
    workspace to write about.

    A wrong slug is refused and recorded as an attempt.

    Answers 204, and there is nothing to return: the workspace this named
    does not exist any more, and neither do its contacts, conversations,
    messages, or its own audit log. What survives is the row in
    `/admin/audit` naming it by slug.
    """
    service.erase_now(actor, workspace_id, confirm_slug=payload.confirm_slug)
