import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.dependencies.staff import StaffAdminDep
from app.api.errors import (
    ADMIN_FORBIDDEN,
    ADMIN_UNAUTHORISED,
    APPROVAL_REQUIRED,
    RATE_LIMITED,
)
from app.models.admin_approval import AdminApproval
from app.models.user import User
from app.schemas.admin_approval import (
    ApprovalPage,
    ApprovalRead,
    ApprovalRequest,
)
from app.services.admin_approval_service import AdminApprovalServiceDep

router = APIRouter(prefix="/approvals", tags=["platform"])

PLATFORM = {**ADMIN_UNAUTHORISED, **ADMIN_FORBIDDEN, **RATE_LIMITED}


# `admin`, not `owner`, and that is deliberate: the point of a second
# person is that there is a second person, and requiring the platform's
# most senior rank to agree would make the control unusable in exactly
# the deployments that need it most -- the small ones, with one owner.
#
# What owner-only would buy is that only owners can second an owner
# promotion. What it costs is that a single-owner platform could never
# promote anybody, which is worse.
@router.post("", status_code=status.HTTP_201_CREATED, responses=PLATFORM)
def request_approval(
    payload: ApprovalRequest,
    actor: StaffAdminDep,
    service: AdminApprovalServiceDep,
) -> ApprovalRead:
    """Ask for a colleague's agreement to one specific act.

    The subject is part of what is being agreed to: a colleague who says
    yes to erasing a test workspace has not said yes to erasing any of
    them.

    Short-lived by configuration. The point of a second person is that
    they are looking at the same situation, and an approval collected in
    the morning and spent in the evening is one signature on a decision
    rather than two.
    """
    return _read(
        service.request(
            actor.logged,
            action=payload.action,
            subject=payload.subject,
            reason=payload.reason,
            meta={"role": payload.role} if payload.role else {},
        ),
        requested_by=actor.user,
        approved_by=None,
    )


@router.post(
    "/{approval_id}/approve",
    responses={**PLATFORM, **APPROVAL_REQUIRED},
)
def approve_request(
    approval_id: uuid.UUID,
    actor: StaffAdminDep,
    service: AdminApprovalServiceDep,
) -> ApprovalRead:
    """Agree to somebody else's request.

    Refused on your own, which is the control rather than a formality: an
    approval you raised and agreed to yourself is a form with extra
    steps.

    Agreeing is not performing. Whoever spends this must be somebody
    other than you, so the ordinary shape is that a colleague asks, you
    agree, and they act.
    """
    return _read(
        service.approve(actor.logged, approval_id),
        requested_by=None,
        approved_by=actor.user,
    )


@router.get("", responses=PLATFORM)
def list_approvals(
    actor: StaffAdminDep,
    service: AdminApprovalServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ApprovalPage:
    """The review surface for the two most serious acts on the platform.

    Spent and expired ones included, which is most of the value: a list
    of only what is pending is almost always empty, and the question
    being asked is what has been agreed to.
    """
    found, total = service.listed(actor.logged, page=page, page_size=page_size)

    return ApprovalPage(
        items=[
            _read(approval, requested_by=asked, approved_by=agreed)
            for approval, asked, agreed in found
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


def _read(
    approval: AdminApproval,
    *,
    requested_by: User | None,
    approved_by: User | None,
) -> ApprovalRead:
    return ApprovalRead(
        id=approval.id,
        action=approval.action,
        subject=approval.subject,
        reason=approval.reason,
        requested_by=requested_by.email if requested_by else None,
        approved_by=approved_by.email if approved_by else None,
        approved_at=approval.approved_at,
        consumed_at=approval.consumed_at,
        expires_at=approval.expires_at,
        created_at=approval.created_at,
        metadata=approval.meta,
        usable=approval.usable_at(datetime.now(UTC)),
    )
