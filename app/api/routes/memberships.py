from fastapi import APIRouter, status

from app.api.dependencies.workspace import WorkspaceAdminDep, WorkspaceMemberDep
from app.api.errors import (
    MEMBER_CONFLICT,
    MEMBER_NOT_FOUND,
    UNAUTHORISED,
    WORKSPACE_FORBIDDEN,
    WORKSPACE_NOT_FOUND,
)
from app.models.user import User
from app.models.workspace_membership import WorkspaceMembership
from app.schemas.workspace_membership import MemberRead, MemberUpdate
from app.services.membership_service import MembershipServiceDep

router = APIRouter(
    prefix="/workspaces/{workspace_id}/members",
    tags=["members"],
)

SCOPED = {**UNAUTHORISED, **WORKSPACE_FORBIDDEN, **WORKSPACE_NOT_FOUND}


def _read(membership: WorkspaceMembership, user: User) -> MemberRead:
    return MemberRead(
        user_id=user.id,
        name=user.name,
        email=user.email,
        role=membership.role,
        status=membership.status,
        joined_at=membership.created_at,
    )


# The role each route needs is in its signature rather than in its body.
# WorkspaceMemberDep and WorkspaceAdminDep both resolve the workspace and
# the caller's membership first, so reaching a handler at all already means
# the tenant check passed.
@router.get("", responses=SCOPED)
def list_members(
    access: WorkspaceMemberDep,
    service: MembershipServiceDep,
) -> list[MemberRead]:
    """Who is on the team. Any member may see who they work with.

    Unpaginated on purpose: a workspace's team is people, and the plans
    this is built for cap that in the low tens. The conversation and
    contact lists, which are not bounded that way, are paginated.
    """
    return [
        _read(membership, user) for membership, user in service.list_members(access)
    ]


@router.patch(
    "/{user_id}",
    responses={**SCOPED, **MEMBER_NOT_FOUND, **MEMBER_CONFLICT},
)
def change_member_role(
    user_id: int,
    payload: MemberUpdate,
    access: WorkspaceAdminDep,
    service: MembershipServiceDep,
) -> MemberRead:
    membership, user = service.change_role(access, user_id, payload.role)

    return _read(membership, user)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**SCOPED, **MEMBER_NOT_FOUND, **MEMBER_CONFLICT},
)
def remove_member(
    user_id: int,
    access: WorkspaceMemberDep,
    service: MembershipServiceDep,
) -> None:
    """Remove somebody, or leave the workspace yourself.

    Any member may leave; removing somebody else needs a role above
    theirs, which is why this takes WorkspaceMemberDep and settles the
    rest in the service rather than refusing at the door.
    """
    service.remove(access, user_id)
