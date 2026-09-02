from fastapi import APIRouter, status

from app.api.dependencies.staff import StaffAdminDep, StaffDep, StaffOwnerDep
from app.api.errors import (
    ADMIN_FORBIDDEN,
    ADMIN_UNAUTHORISED,
    RATE_LIMITED,
    STAFF_CONFLICT,
    STAFF_NOT_FOUND,
)
from app.models.staff_member import StaffMember
from app.models.user import User
from app.schemas.staff import StaffGrant, StaffRead, StaffUpdate
from app.services.staff_service import StaffServiceDep

router = APIRouter(tags=["platform"])

# Every route here can refuse for the same three reasons, so the three
# are named once. The 429 is in the list because the whole router is
# counted, in app/api/admin_router.py, rather than route by route.
PLATFORM = {**ADMIN_UNAUTHORISED, **ADMIN_FORBIDDEN, **RATE_LIMITED}


def _read(member: StaffMember, user: User) -> StaffRead:
    return StaffRead(
        user_id=user.id,
        name=user.name,
        email=user.email,
        role=member.role,
        granted_by_user_id=member.granted_by_user_id,
        granted_at=member.granted_at,
        revoked_at=member.revoked_at,
    )


# The rank each route needs is in its signature. StaffDep is the whole
# check for the first of them -- being staff at all -- and the two below
# it climb: reading the team is administration, and changing it is the
# one act that creates more of this surface.
@router.get("/me", responses=PLATFORM)
def read_current_staff_member(
    actor: StaffDep,
    service: StaffServiceDep,
) -> StaffRead:
    """Who you are on this platform, and what you may do here.

    The console's first call, and it writes an audit row like every other
    route on this surface. That is not zeal: "who was in the console on
    Tuesday afternoon" is a question this log has to be able to answer
    even about a visit where nothing else was opened.
    """
    return _read(service.whoami(actor), actor.user)


@router.get("/staff", responses=PLATFORM)
def list_staff(
    actor: StaffAdminDep,
    service: StaffServiceDep,
) -> list[StaffRead]:
    """Everybody who runs this platform, revoked rows included.

    Unpaginated, like a workspace's member list: this is people, and
    there are not going to be thousands of them. Revoked rows stay
    because they are the half of the screen somebody needs after an
    incident -- who used to have this, and when it was taken away.
    """
    return [_read(member, user) for member, user in service.list_staff(actor)]


@router.post(
    "/staff",
    status_code=status.HTTP_201_CREATED,
    responses={**PLATFORM, **STAFF_NOT_FOUND, **STAFF_CONFLICT},
)
def grant_staff_access(
    payload: StaffGrant,
    actor: StaffOwnerDep,
    service: StaffServiceDep,
) -> StaffRead:
    """Give an existing account access to the platform.

    Owner only, and that is the line this surface is built around: this
    is the one act that creates more of this surface, and an admin who
    could promote themselves would make the ranks decorative.

    Re-granting to somebody whose access was revoked reinstates their
    row rather than adding a second one, so a colleague who left and came
    back has one history rather than two that have to be read together.
    """
    member, user = service.grant(actor, payload.user_id, payload.role)

    return _read(member, user)


@router.patch(
    "/staff/{user_id}",
    responses={**PLATFORM, **STAFF_NOT_FOUND, **STAFF_CONFLICT},
)
def change_staff_role(
    user_id: int,
    payload: StaffUpdate,
    actor: StaffOwnerDep,
    service: StaffServiceDep,
) -> StaffRead:
    """Move a colleague up or down the ladder.

    Refused if it would leave the platform with no live owner, including
    when the person doing it is that owner. Only an owner may grant
    access, so a platform without one is a console nobody can be added to
    again without a database client.
    """
    member, user = service.change_role(actor, user_id, payload.role)

    return _read(member, user)


@router.delete(
    "/staff/{user_id}",
    responses={**PLATFORM, **STAFF_NOT_FOUND, **STAFF_CONFLICT},
)
def revoke_staff_access(
    user_id: int,
    actor: StaffOwnerDep,
    service: StaffServiceDep,
) -> StaffRead:
    """Take somebody's platform access away.

    Answers with the row rather than 204, like revoking an API key, and
    for the same reason: `revoked_at` is the thing somebody wants to see,
    because it is the difference between having turned this off just now
    and finding that a colleague already had.

    Their sessions are left alone. A staff member is an ordinary account
    with ordinary workspaces, and signing them out of a customer's inbox
    because they no longer run the platform would be this surface
    reaching into the tenant one.
    """
    member, user = service.revoke(actor, user_id)

    return _read(member, user)
