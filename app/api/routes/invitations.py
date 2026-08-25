import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, status

from app.api.dependencies.auth import CurrentUserDep
from app.api.dependencies.workspace import WorkspaceAdminDep
from app.api.errors import (
    INVITATION_CONFLICT,
    INVITATION_FORBIDDEN,
    INVITATION_GONE,
    INVITATION_NOT_FOUND,
    UNAUTHORISED,
    WORKSPACE_FORBIDDEN,
    WORKSPACE_NOT_FOUND,
)
from app.models.workspace_invitation import WorkspaceInvitation
from app.schemas.workspace import WorkspaceRead
from app.schemas.workspace_invitation import (
    InvitationCreate,
    InvitationCreated,
    InvitationPreview,
    InvitationRead,
)
from app.services.invitation_service import InvitationServiceDep

# Sending invitations is administration and lives under the workspace.
# Answering one cannot: whoever holds the link is not a member yet, so
# those two routes hang off the token instead and are their own router.
workspace_router = APIRouter(
    prefix="/workspaces/{workspace_id}/invitations",
    tags=["invitations"],
)

token_router = APIRouter(
    prefix="/invitations",
    tags=["invitations"],
)

SCOPED = {**UNAUTHORISED, **WORKSPACE_FORBIDDEN, **WORKSPACE_NOT_FOUND}


def _read(invitation: WorkspaceInvitation) -> InvitationRead:
    return InvitationRead(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        status=invitation.status_at(datetime.now(UTC)),
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
        created_at=invitation.created_at,
    )


@workspace_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={**SCOPED, **INVITATION_CONFLICT},
)
def invite_member(
    payload: InvitationCreate,
    access: WorkspaceAdminDep,
    service: InvitationServiceDep,
) -> InvitationCreated:
    """Invite somebody to the workspace.

    The response carries the token, and this is the only response that
    ever will: what is stored is a digest, so it cannot be produced again
    from the database. Once there is an email to put the link in, that is
    where it should go and this field should stop being returned.
    """
    invitation, token = service.invite(access, payload)

    return InvitationCreated(**_read(invitation).model_dump(), token=token)


@workspace_router.get("", responses=SCOPED)
def list_invitations(
    access: WorkspaceAdminDep,
    service: InvitationServiceDep,
) -> list[InvitationRead]:
    """Every invitation this workspace has sent, newest first.

    Behind the admin dependency rather than open to any member: it is a
    list of the addresses of people being recruited, which is not
    everybody's business.
    """
    return [_read(invitation) for invitation in service.list_for(access)]


@workspace_router.delete(
    "/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**SCOPED, **INVITATION_NOT_FOUND},
)
def revoke_invitation(
    invitation_id: uuid.UUID,
    access: WorkspaceAdminDep,
    service: InvitationServiceDep,
) -> None:
    """Withdraw an invitation, which makes its link stop working.

    This does not remove somebody who has already accepted; by then they
    are a member, and members are removed through the members API.
    """
    service.revoke(access, invitation_id)


@token_router.get("/{token}", responses=INVITATION_NOT_FOUND)
def preview_invitation(
    token: str,
    service: InvitationServiceDep,
) -> InvitationPreview:
    """What the link says, before anyone commits to anything.

    The one route here that takes no token of its own: the person reading
    it may not have an account yet, which is the point of inviting them.
    """
    invitation, workspace = service.preview(token)

    return InvitationPreview(
        workspace_name=workspace.name,
        workspace_slug=workspace.slug,
        email=invitation.email,
        role=invitation.role,
        status=invitation.status_at(datetime.now(UTC)),
        expires_at=invitation.expires_at,
    )


@token_router.post(
    "/{token}/accept",
    responses={
        **UNAUTHORISED,
        **INVITATION_FORBIDDEN,
        **INVITATION_NOT_FOUND,
        **INVITATION_GONE,
        **INVITATION_CONFLICT,
    },
)
def accept_invitation(
    token: str,
    user: CurrentUserDep,
    service: InvitationServiceDep,
) -> WorkspaceRead:
    """Take the seat, and get back the workspace just joined.

    Requires an account, because a membership has to belong to somebody.
    Signing up first and accepting second is the flow; the invitation
    only admits the address it was sent to.
    """
    _, workspace = service.accept(token, user)

    return WorkspaceRead.model_validate(workspace)
