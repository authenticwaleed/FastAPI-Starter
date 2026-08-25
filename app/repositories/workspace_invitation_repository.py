import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.workspace_invitation import WorkspaceInvitation
from app.models.workspace_membership import WorkspaceRole


class WorkspaceInvitationRepository:
    """Every query against the workspace_invitations table lives here."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        workspace_id: uuid.UUID,
        email: str,
        role: WorkspaceRole,
        token_hash: str,
        expires_at: datetime,
        invited_by_user_id: int,
    ) -> WorkspaceInvitation:
        invitation = WorkspaceInvitation(
            workspace_id=workspace_id,
            email=email,
            role=role,
            token_hash=token_hash,
            expires_at=expires_at,
            invited_by_user_id=invited_by_user_id,
        )

        self._session.add(invitation)
        self._session.flush()

        return invitation

    def get_by_token_hash(self, token_hash: str) -> WorkspaceInvitation | None:
        """The one indexed lookup that acceptance costs.

        Possible because the digest is unsalted -- see `hash_token`.
        """
        return self._session.scalar(
            select(WorkspaceInvitation).where(
                WorkspaceInvitation.token_hash == token_hash
            )
        )

    def get_in_workspace(
        self,
        workspace_id: uuid.UUID,
        invitation_id: uuid.UUID,
    ) -> WorkspaceInvitation | None:
        """Scoped by workspace, not looked up by id alone.

        An id is a guess anybody can make. Requiring it to sit in the
        workspace the caller was already admitted to is what stops one
        business revoking another's invitations.
        """
        return self._session.scalar(
            select(WorkspaceInvitation).where(
                WorkspaceInvitation.id == invitation_id,
                WorkspaceInvitation.workspace_id == workspace_id,
            )
        )

    def get_outstanding_for_email(
        self,
        workspace_id: uuid.UUID,
        email: str,
        now: datetime,
    ) -> WorkspaceInvitation | None:
        """An unaccepted, unexpired invitation to this address, if any."""
        return self._session.scalar(
            select(WorkspaceInvitation).where(
                WorkspaceInvitation.workspace_id == workspace_id,
                WorkspaceInvitation.email == email,
                WorkspaceInvitation.accepted_at.is_(None),
                WorkspaceInvitation.expires_at > now,
            )
        )

    def list_for_workspace(
        self,
        workspace_id: uuid.UUID,
    ) -> Sequence[WorkspaceInvitation]:
        """Newest first: the one just sent is the one being looked for."""
        return self._session.scalars(
            select(WorkspaceInvitation)
            .where(WorkspaceInvitation.workspace_id == workspace_id)
            .order_by(
                WorkspaceInvitation.created_at.desc(),
                WorkspaceInvitation.email,
            )
        ).all()

    def mark_accepted(
        self,
        invitation: WorkspaceInvitation,
        at: datetime,
    ) -> WorkspaceInvitation:
        invitation.accepted_at = at
        self._session.flush()

        return invitation

    def delete(self, invitation: WorkspaceInvitation) -> None:
        self._session.delete(invitation)
        self._session.flush()
