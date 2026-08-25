import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column


class WorkspaceRole(StrEnum):
    """The four MVP roles, in descending order of what they may do.

    Deliberately a fixed list rather than a permission engine. Four names
    cover what a small support team actually needs, and a dynamic
    permission system is a product in its own right.
    """

    OWNER = "owner"
    ADMIN = "admin"
    AGENT = "agent"
    VIEWER = "viewer"


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    # Set rather than deleting the row, so that re-adding somebody restores
    # the membership they had instead of colliding with it. Nothing writes
    # this yet: removing a member is part of managing them, which needs the
    # role checks of the next phase.
    REMOVED = "removed"


class WorkspaceMembership(Base):
    """Which users belong to which business, and what they may do there."""

    __tablename__ = "workspace_memberships"

    __table_args__ = (
        # One membership per person per workspace. This is what makes
        # "re-add a removed member" an update rather than a second row with
        # a different role, and what stops a double-accepted invitation
        # granting two.
        UniqueConstraint(
            "workspace_id",
            "user_id",
            name="uq_workspace_memberships_workspace_id_user_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    # CASCADE on both sides: a membership is meaningless without the
    # workspace or the person it connects, so it should never outlive
    # either. Note that cancelling a workspace is not deleting it, so
    # cancellation leaves these rows alone.
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    role: Mapped[WorkspaceRole] = mapped_column(
        enum_column(WorkspaceRole, name="workspace_role"),
    )

    status: Mapped[MembershipStatus] = mapped_column(
        enum_column(MembershipStatus, name="membership_status"),
        default=MembershipStatus.ACTIVE,
        server_default=text("'active'"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"WorkspaceMembership(workspace_id={self.workspace_id!r}, "
            f"user_id={self.user_id!r}, role={self.role!r})"
        )
