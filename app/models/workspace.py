import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column


class WorkspaceStatus(StrEnum):
    ACTIVE = "active"
    # Reachable but frozen -- an unpaid bill, an abuse investigation.
    SUSPENDED = "suspended"
    # What DELETE leaves behind. The rows stay: a workspace will soon own
    # contacts, conversations and message history, and a customer's records
    # should not be destroyed by one call to one endpoint. Erasing them for
    # real is a deliberate workflow, not a side effect.
    CANCELLED = "cancelled"


class Workspace(Base):
    """One customer business. The tenant boundary everything else hangs off."""

    __tablename__ = "workspaces"

    # A UUID rather than a sequence, because this id is in the path of every
    # tenant-scoped URL. A sequential id there would tell anyone who signs up
    # roughly how many businesses use the product and let them walk the range
    # to see which ids answer differently.
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(String(100))

    # A DNS label's length, because that is what a slug is eventually for.
    slug: Mapped[str] = mapped_column(String(63), unique=True)

    status: Mapped[WorkspaceStatus] = mapped_column(
        enum_column(WorkspaceStatus, name="workspace_status"),
        default=WorkspaceStatus.ACTIVE,
        server_default=text("'active'"),
    )

    # An IANA name, validated at the schema. Analytics and business-hours
    # rules are reported in the business's own time, not the server's.
    timezone: Mapped[str] = mapped_column(
        String(64),
        default="UTC",
        server_default=text("'UTC'"),
    )

    # ISO 4217.
    default_currency: Mapped[str] = mapped_column(
        String(3),
        default="USD",
        server_default=text("'USD'"),
    )

    # An audit field, nullable on purpose. If the creator later deletes their
    # account the business carries on without them, so this goes null rather
    # than taking the workspace with it. Who may administer it is a question
    # for the memberships table, not this column.
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
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
        return f"Workspace(id={self.id!r}, slug={self.slug!r})"
