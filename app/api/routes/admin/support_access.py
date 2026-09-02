import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, status

from app.api.dependencies.staff import StaffAdminDep, StaffDep
from app.api.errors import (
    ADMIN_NOT_FOUND,
    ADMIN_UNAUTHORISED,
    BAD_GRANT_DURATION,
    RATE_LIMITED,
    SUPPORT_ACCESS_FORBIDDEN,
    SUPPORT_GRANT_CONFLICT,
)
from app.models.support_grant import SupportGrant
from app.models.user import User
from app.schemas.support_access import SupportAccessRequest, SupportGrantRead
from app.services.support_access_service import SupportAccessServiceDep

router = APIRouter(
    prefix="/workspaces/{workspace_id}/support-access", tags=["platform"]
)

PLATFORM = {
    **ADMIN_UNAUTHORISED,
    **SUPPORT_ACCESS_FORBIDDEN,
    **RATE_LIMITED,
    **ADMIN_NOT_FOUND,
}


# Asking for access is `support`, and seeing who has had it is `admin`.
# That split is the point rather than an accident: the rank that answers
# tickets is the rank that needs to look at accounts, and the rank that
# oversees them is the one that reviews whether they should have.
@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={**PLATFORM, **SUPPORT_GRANT_CONFLICT, **BAD_GRANT_DURATION},
)
def request_support_access(
    workspace_id: uuid.UUID,
    payload: SupportAccessRequest,
    actor: StaffDep,
    service: SupportAccessServiceDep,
) -> SupportGrantRead:
    """Open a time-boxed window on this customer's data.

    Nothing about this is quiet. The grant is written down, the customer
    sees it in their own audit log with the reason given here, and every
    read it later permits is recorded separately.

    It ends on its own. Nothing has to run for that to happen -- an
    expired grant simply stops matching the lookup that opens the door.
    """
    return _read(
        service.grant(
            actor,
            workspace_id,
            reason=payload.reason,
            hours=payload.hours,
        ),
        actor.user,
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, responses=PLATFORM)
def end_support_access(
    workspace_id: uuid.UUID,
    actor: StaffDep,
    service: SupportAccessServiceDep,
) -> None:
    """Close your own window before it runs out.

    Always 204, whether there was a live grant or not. Ending access you
    no longer hold is not an error, and somebody closing a window they
    have finished with should not have to know whether it had already
    expired -- a refusal would be a confusing answer to the safest
    request on this surface.

    Ends your own grant and only yours. Taking a colleague's access away
    is a different act with a different rank behind it, and it is not in
    this phase.
    """
    service.revoke(actor, workspace_id)


@router.get("", responses=PLATFORM)
def list_support_access(
    workspace_id: uuid.UUID,
    actor: StaffAdminDep,
    service: SupportAccessServiceDep,
) -> list[SupportGrantRead]:
    """Who has been in this account, when, and why.

    History as well as what is live, because a list of only the live ones
    is almost always empty and the question is about the past. This is
    the review surface for the power the two routes above hand out.
    """
    return [
        _read(grant, user) for grant, user in service.list_grants(actor, workspace_id)
    ]


def _read(grant: SupportGrant, staff: User) -> SupportGrantRead:
    """One grant, with `live` worked out rather than stored.

    From the two timestamps and the clock, which is the only place the
    three meet -- a stored flag would be a third thing to keep in step
    with them, and the one that would eventually be wrong.
    """
    return SupportGrantRead(
        id=grant.id,
        workspace_id=grant.workspace_id,
        staff_user_id=grant.staff_user_id,
        staff_email=staff.email,
        reason=grant.reason,
        expires_at=grant.expires_at,
        revoked_at=grant.revoked_at,
        created_at=grant.created_at,
        live=grant.is_live_at(datetime.now(UTC)),
    )
