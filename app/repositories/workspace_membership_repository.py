import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.workspace import Workspace, WorkspaceStatus
from app.models.workspace_membership import (
    MembershipStatus,
    WorkspaceMembership,
    WorkspaceRole,
)


class WorkspaceMembershipRepository:
    """Every query against the workspace_memberships table lives here."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        workspace_id: uuid.UUID,
        user_id: int,
        role: WorkspaceRole,
    ) -> WorkspaceMembership:
        membership = WorkspaceMembership(
            workspace_id=workspace_id,
            user_id=user_id,
            role=role,
        )

        self._session.add(membership)
        self._session.flush()

        return membership

    def get_for_user(
        self,
        workspace_id: uuid.UUID,
        user_id: int,
    ) -> WorkspaceMembership | None:
        """This user's membership of this workspace, active or not.

        The status is returned rather than filtered so the caller can tell
        "was removed" from "never belonged". Both are refused, but only one
        of them is worth a different log line.
        """
        return self._session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user_id,
            )
        )

    def list_for_workspace(
        self,
        workspace_id: uuid.UUID,
    ) -> Sequence[WorkspaceMembership]:
        return self._session.scalars(
            select(WorkspaceMembership)
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.status == MembershipStatus.ACTIVE,
            )
            .order_by(WorkspaceMembership.created_at, WorkspaceMembership.id)
        ).all()

    def get_with_user(
        self,
        workspace_id: uuid.UUID,
        user_id: int,
    ) -> tuple[WorkspaceMembership, User] | None:
        """One membership with the person behind it, active or not."""
        row = self._session.execute(
            select(WorkspaceMembership, User)
            .join(User, User.id == WorkspaceMembership.user_id)
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user_id,
            )
        ).first()

        if row is None:
            return None

        membership, user = row

        return membership, user

    def list_with_users(
        self,
        workspace_id: uuid.UUID,
    ) -> list[tuple[WorkspaceMembership, User]]:
        """The workspace's active members, each with the person behind it.

        One join rather than a membership list followed by a user lookup
        per row. A team is small, but a query per member is the habit that
        makes the conversation list unusable later.
        """
        rows = self._session.execute(
            select(WorkspaceMembership, User)
            .join(User, User.id == WorkspaceMembership.user_id)
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.status == MembershipStatus.ACTIVE,
            )
            .order_by(
                WorkspaceMembership.created_at,
                # Not the membership id: it is a UUID, and rows written in
                # one transaction share a created_at, so it would break
                # ties at random. user_id is sequential and means
                # something -- who joined the platform first.
                WorkspaceMembership.user_id,
            )
        ).all()

        return [(membership, user) for membership, user in rows]

    def count_active_owners(self, workspace_id: uuid.UUID) -> int:
        """How many owners the workspace would still have without this one.

        Asked before every demotion and removal. A workspace whose last
        owner leaves is one its own members are locked out of.
        """
        return (
            self._session.scalar(
                select(func.count())
                .select_from(WorkspaceMembership)
                .where(
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembership.role == WorkspaceRole.OWNER,
                    WorkspaceMembership.status == MembershipStatus.ACTIVE,
                )
            )
            or 0
        )

    def set_role(
        self,
        membership: WorkspaceMembership,
        role: WorkspaceRole,
    ) -> WorkspaceMembership:
        membership.role = role
        self._session.flush()

        return membership

    def set_status(
        self,
        membership: WorkspaceMembership,
        status: MembershipStatus,
    ) -> WorkspaceMembership:
        membership.status = status
        self._session.flush()

        return membership

    def sole_owned_workspace_ids(self, user_id: int) -> list[uuid.UUID]:
        """Live workspaces where this user is the only remaining owner.

        Asked before an account is deleted. Letting the last owner go would
        leave a business no one can administer, with no way back in, so the
        answer to this decides whether that deletion is allowed to proceed.

        Cancelled workspaces are excluded: nobody needs to keep an account
        alive to administer a business that is already closed.
        """
        owner_counts = (
            select(
                WorkspaceMembership.workspace_id.label("workspace_id"),
                func.count().label("owners"),
            )
            .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
            .where(
                WorkspaceMembership.role == WorkspaceRole.OWNER,
                WorkspaceMembership.status == MembershipStatus.ACTIVE,
                Workspace.status != WorkspaceStatus.CANCELLED,
            )
            .group_by(WorkspaceMembership.workspace_id)
            .subquery()
        )

        return list(
            self._session.scalars(
                select(WorkspaceMembership.workspace_id)
                .join(
                    owner_counts,
                    owner_counts.c.workspace_id == WorkspaceMembership.workspace_id,
                )
                .where(
                    WorkspaceMembership.user_id == user_id,
                    WorkspaceMembership.role == WorkspaceRole.OWNER,
                    WorkspaceMembership.status == MembershipStatus.ACTIVE,
                    owner_counts.c.owners == 1,
                )
            ).all()
        )
