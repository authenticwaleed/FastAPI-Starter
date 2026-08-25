import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import (
    AlreadyAMemberError,
    InsufficientWorkspaceRoleError,
    InvitationAlreadyAcceptedError,
    InvitationExpiredError,
    InvitationNotFoundError,
    InvitationNotYoursError,
    PendingInvitationExistsError,
)
from app.core.security import generate_token, hash_token
from app.db.session import SessionDep
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceStatus
from app.models.workspace_invitation import WorkspaceInvitation
from app.models.workspace_membership import (
    MembershipStatus,
    WorkspaceMembership,
)
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_invitation_repository import (
    WorkspaceInvitationRepository,
)
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.workspace_invitation import InvitationCreate
from app.services.membership_service import may_manage
from app.services.user_service import UserRepositoryDep
from app.services.workspace_service import (
    WorkspaceAccess,
    WorkspaceMembershipRepositoryDep,
    WorkspaceRepositoryDep,
)


class InvitationService:
    """Offering somebody a seat in a workspace, and letting them take it.

    The two halves are deliberately asymmetric. Sending an invitation is
    administration and runs behind the workspace dependency, on a
    WorkspaceAccess that has already been resolved. Accepting one cannot:
    the person doing it is not a member yet, so the token is the only
    thing vouching for them, and every check that would normally have
    happened at the door happens here instead.
    """

    def __init__(
        self,
        session: Session,
        invitations: WorkspaceInvitationRepository,
        memberships: WorkspaceMembershipRepository,
        workspaces: WorkspaceRepository,
        users: UserRepository,
    ) -> None:
        self._session = session
        self._invitations = invitations
        self._memberships = memberships
        self._workspaces = workspaces
        self._users = users

    # --- sending ------------------------------------------------------

    def invite(
        self,
        access: WorkspaceAccess,
        payload: InvitationCreate,
    ) -> tuple[WorkspaceInvitation, str]:
        """Create an invitation, returning it with its one readable token.

        The role being offered goes through the same rank rule as changing
        somebody's role does. Without that, an admin who cannot promote a
        colleague to admin could simply invite a second account at that
        rank instead, and the ceiling would not be a ceiling.
        """
        if not may_manage(access.role, payload.role):
            raise InsufficientWorkspaceRoleError(access.workspace.id, access.role)

        now = datetime.now(UTC)

        self._refuse_if_already_a_member(access.workspace.id, payload.email)

        outstanding = self._invitations.get_outstanding_for_email(
            access.workspace.id,
            payload.email,
            now,
        )

        if outstanding is not None:
            raise PendingInvitationExistsError(access.workspace.id, payload.email)

        # The only moment this value exists in readable form. What is
        # stored is its digest, so nothing after this can reproduce it.
        token = generate_token()

        invitation = self._invitations.create(
            workspace_id=access.workspace.id,
            email=payload.email,
            role=payload.role,
            token_hash=hash_token(token),
            expires_at=now + timedelta(hours=get_settings().invitation_expire_hours),
            invited_by_user_id=access.membership.user_id,
        )
        self._session.commit()

        return invitation, token

    def list_for(self, access: WorkspaceAccess) -> Sequence[WorkspaceInvitation]:
        return self._invitations.list_for_workspace(access.workspace.id)

    def revoke(self, access: WorkspaceAccess, invitation_id: uuid.UUID) -> None:
        """Withdraw an invitation.

        The row goes rather than being marked withdrawn, which is what
        makes the same address invitable again straight away. Note this
        does not undo an invitation already accepted: that person is a
        member now, and removing a member is the members API's job.
        """
        invitation = self._invitations.get_in_workspace(
            access.workspace.id,
            invitation_id,
        )

        if invitation is None:
            raise InvitationNotFoundError

        self._invitations.delete(invitation)
        self._session.commit()

    # --- receiving ----------------------------------------------------

    def preview(self, token: str) -> tuple[WorkspaceInvitation, Workspace]:
        """What the link shows before anyone commits to anything.

        Unauthenticated, because the person reading it may not have an
        account yet -- which is the whole point of inviting them.
        """
        return self._usable(token)

    def accept(self, token: str, user: User) -> tuple[WorkspaceMembership, Workspace]:
        invitation, workspace = self._usable(token)

        if invitation.accepted_at is not None:
            raise InvitationAlreadyAcceptedError

        if invitation.expires_at <= datetime.now(UTC):
            raise InvitationExpiredError

        if user.email.lower() != invitation.email:
            raise InvitationNotYoursError

        existing = self._memberships.get_for_user(workspace.id, user.id)

        if existing is not None and existing.status == MembershipStatus.ACTIVE:
            raise AlreadyAMemberError(workspace.id, invitation.email)

        try:
            if existing is not None:
                # They were here before and were removed. The unique
                # constraint means there is one row per person per
                # workspace, so coming back is that row being restored
                # with whatever role this invitation offers.
                self._memberships.set_role(existing, invitation.role)
                membership = self._memberships.set_status(
                    existing,
                    MembershipStatus.ACTIVE,
                )
            else:
                membership = self._memberships.create(
                    workspace_id=workspace.id,
                    user_id=user.id,
                    role=invitation.role,
                )

            # In the same transaction as the membership, which is what
            # makes acceptance single-use: two requests racing the same
            # link cannot both come away with a seat.
            self._invitations.mark_accepted(invitation, datetime.now(UTC))
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise AlreadyAMemberError(workspace.id, invitation.email) from exc

        return membership, workspace

    # --- shared -------------------------------------------------------

    def _usable(self, token: str) -> tuple[WorkspaceInvitation, Workspace]:
        """Resolve a token to an invitation whose workspace still exists.

        A revoked invitation and one that never existed are the same
        answer, and so is one whose workspace has since been closed: the
        holder has proved nothing yet, so none of those distinctions are
        theirs to have.
        """
        invitation = self._invitations.get_by_token_hash(hash_token(token))

        if invitation is None:
            raise InvitationNotFoundError

        workspace = self._workspaces.get(invitation.workspace_id)

        if workspace is None or workspace.status == WorkspaceStatus.CANCELLED:
            raise InvitationNotFoundError

        return invitation, workspace

    def _refuse_if_already_a_member(self, workspace_id: uuid.UUID, email: str) -> None:
        user = self._users.get_by_email(email)

        if user is None:
            # No account yet, which is the ordinary case for an invitation.
            return

        membership = self._memberships.get_for_user(workspace_id, user.id)

        if membership is not None and membership.status == MembershipStatus.ACTIVE:
            raise AlreadyAMemberError(workspace_id, email)


def get_workspace_invitation_repository(
    session: SessionDep,
) -> WorkspaceInvitationRepository:
    return WorkspaceInvitationRepository(session)


WorkspaceInvitationRepositoryDep = Annotated[
    WorkspaceInvitationRepository,
    Depends(get_workspace_invitation_repository),
]


def get_invitation_service(
    session: SessionDep,
    invitations: WorkspaceInvitationRepositoryDep,
    memberships: WorkspaceMembershipRepositoryDep,
    workspaces: WorkspaceRepositoryDep,
    users: UserRepositoryDep,
) -> InvitationService:
    return InvitationService(
        session=session,
        invitations=invitations,
        memberships=memberships,
        workspaces=workspaces,
        users=users,
    )


InvitationServiceDep = Annotated[InvitationService, Depends(get_invitation_service)]
