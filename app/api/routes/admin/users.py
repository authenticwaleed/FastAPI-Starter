from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies.staff import StaffDep
from app.api.errors import (
    ADMIN_FORBIDDEN,
    ADMIN_NOT_FOUND,
    ADMIN_UNAUTHORISED,
    RATE_LIMITED,
)
from app.models.user import User
from app.models.user_session import UserSession
from app.models.workspace import Workspace
from app.models.workspace_membership import WorkspaceMembership
from app.schemas.admin_console import (
    AdminUserDetail,
    AdminUserMembership,
    AdminUserPage,
    AdminUserSession,
    AdminUserSummary,
)
from app.services.admin_user_service import AdminUserServiceDep

router = APIRouter(prefix="/users", tags=["platform"])

PLATFORM = {**ADMIN_UNAUTHORISED, **ADMIN_FORBIDDEN, **RATE_LIMITED}


# There is no POST here, and there will not be one. Staff are ordinary
# accounts that have been promoted, and so is everybody else -- an
# endpoint on this surface that created a user would be a way to make an
# account nobody consented to, with a password only the platform knows.
@router.get("", responses=PLATFORM)
def search_users(
    actor: StaffDep,
    service: AdminUserServiceDep,
    q: Annotated[str | None, Query(max_length=320)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AdminUserPage:
    """Find an account by address or name.

    Either matching anywhere in the value, because a ticket arrives with
    a fragment -- half a company address, a first name as it is spelled
    in a signature -- and almost never with an id.
    """
    found, total = service.search(actor, term=q, page=page, page_size=page_size)

    return AdminUserPage(
        items=[_summary(user) for user in found],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{user_id}", responses={**PLATFORM, **ADMIN_NOT_FOUND})
def read_user(
    user_id: int,
    actor: StaffDep,
    service: AdminUserServiceDep,
) -> AdminUserDetail:
    """One account, the workspaces it belongs to, and where it is signed in.

    The three things a "I cannot get in" ticket needs at once: whether
    the account is active, whether it is really in the business it says
    it is, and whether anything is signed in at all.

    An account with no workspaces and no sessions answers with two empty
    lists rather than refusing. That is a real and common state -- it is
    what somebody who registered and never went further looks like.
    """
    user, memberships, sessions = service.read(actor, user_id)

    return AdminUserDetail(
        **_summary(user).model_dump(),
        memberships=[
            _membership(membership, workspace) for membership, workspace in memberships
        ],
        sessions=[_session(session) for session in sessions],
    )


def _summary(user: User) -> AdminUserSummary:
    return AdminUserSummary(
        id=user.id,
        name=user.name,
        email=user.email,
        is_active=user.is_active,
        email_verified_at=user.email_verified_at,
        created_at=user.created_at,
    )


def _membership(
    membership: WorkspaceMembership,
    workspace: Workspace,
) -> AdminUserMembership:
    """One workspace this account belongs to, or used to.

    The workspace's status travels with the membership's, because the two
    together are the answer: "removed from a business that has since
    closed" and "still an admin of a live one" are different tickets.
    """
    return AdminUserMembership(
        workspace_id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        workspace_status=workspace.status,
        role=membership.role,
        status=membership.status,
        joined_at=membership.created_at,
    )


def _session(session: UserSession) -> AdminUserSession:
    """One live sign-in, without the secret that keeps it alive.

    What is stored for a session is a digest of its refresh token, and
    nothing anywhere returns it -- so there is nothing to withhold here
    beyond what the account's own session list already withholds.
    """
    return AdminUserSession(
        id=session.id,
        created_at=session.created_at,
        last_used_at=session.last_used_at,
        expires_at=session.expires_at,
        user_agent=session.user_agent,
        ip_address=session.ip_address,
    )
