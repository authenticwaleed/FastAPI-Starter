import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column
from app.models.workspace_membership import WorkspaceRole


class InvitationStatus(StrEnum):
    """Not a column. Derived from two timestamps and the clock.

    Storing it as well would be a fourth thing that could disagree with
    them -- an invitation marked pending whose expiry passed an hour ago.
    """

    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"


class WorkspaceInvitation(Base):
    """An outstanding offer to join a workspace.

    Deliberately has no status column. Its state is a function of two
    timestamps and the clock -- accepted, expired, or still open -- and a
    stored status would be a fourth thing that could disagree with them.
    """

    __tablename__ = "workspace_invitations"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )

    # Stored lowercased, so that matching the address against the account
    # accepting the invitation does not turn on how somebody typed it.
    email: Mapped[str] = mapped_column(String(320), index=True)

    role: Mapped[WorkspaceRole] = mapped_column(
        enum_column(WorkspaceRole, name="invitation_role"),
    )

    # The hash of the token, never the token. Anyone reading this table --
    # a backup, a support query, a leaked dump -- must not come away with a
    # set of working invitation links. Unique so the lookup on acceptance
    # is one indexed query, and so a repeat digest cannot silently exist.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # Null until used. Set once, which is what makes acceptance single-use.
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

    # An audit field, like workspaces.created_by_user_id: if the person who
    # sent the invitation later closes their account, the invitation they
    # sent is still valid and the workspace still wants it honoured.
    invited_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    def status_at(self, now: datetime) -> InvitationStatus:
        """What this invitation is, as of `now`.

        The clock is passed in rather than read here, so that a test can
        ask what an invitation looks like next week without waiting.
        """
        if self.accepted_at is not None:
            return InvitationStatus.ACCEPTED

        if self.expires_at <= now:
            return InvitationStatus.EXPIRED

        return InvitationStatus.PENDING

    def __repr__(self) -> str:
        return (
            f"WorkspaceInvitation(id={self.id!r}, "
            f"workspace_id={self.workspace_id!r}, role={self.role!r})"
        )
