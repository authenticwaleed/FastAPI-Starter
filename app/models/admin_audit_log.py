import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column


class AdminAction(StrEnum):
    """Something a staff member did on the platform's own surface.

    Same shape of name as AuditEvent -- `noun.verb`, past tense -- and a
    different vocabulary on purpose. A tenant's log says what a business
    did to itself; this one says what the people running the product did
    to a business, or to each other.

    Reads are in here, which is the difference that matters. On the
    tenant surface, looking at your own data is the work and only changes
    are worth recording. On this one, looking at somebody else's data is
    the sensitive act, and a log that recorded only writes would answer
    the wrong question.
    """

    # The console asking who is holding this session. Recorded like
    # everything else, because "who was in the console on Tuesday" is a
    # question this log has to be able to answer even about a visit where
    # nothing was opened.
    CONSOLE_OPENED = "console.opened"

    STAFF_LISTED = "staff.listed"
    STAFF_GRANTED = "staff.granted"
    STAFF_ROLE_CHANGED = "staff.role_changed"
    STAFF_REVOKED = "staff.revoked"

    # Reading this log is itself an administrative act on this surface,
    # and there is no route at any role that can remove the row.
    AUDIT_READ = "audit.read"


class AdminAuditLog(Base):
    """What staff did, kept apart from what tenants did.

    A second table rather than a widening of `audit_logs`, and the reason
    is not tidiness. The tenant log's workspace reference is NOT NULL and
    ON DELETE CASCADE, and both are right for what it holds: an entry
    belongs to one business, and a business that asked to be forgotten
    should have its history forgotten with it.

    Neither is right here. "Granted a colleague staff access" belongs to
    no workspace at all, so there would be nowhere to put it. And the
    most important row this table will ever hold is "a staff member read
    this workspace two days before it was erased" -- which CASCADE would
    destroy at exactly the moment somebody came looking for it.

    So the workspace reference is nullable, it does not cascade, and the
    slug is copied alongside it. A row here outlives its subject and can
    still name it.
    """

    __tablename__ = "admin_audit_logs"

    __table_args__ = (
        # The console's own list: everything, newest first. Ordered by
        # the sequence rather than the timestamp for the reason the
        # column exists -- see below.
        Index("ix_admin_audit_logs_sequence", text("sequence DESC")),
        # What was done to one business, which is the question a customer
        # asks about their own account and the one a support ticket ends
        # at.
        Index(
            "ix_admin_audit_logs_workspace_id_sequence",
            "workspace_id",
            text("sequence DESC"),
        ),
        # What one staff member did, which is where an investigation
        # starts.
        Index(
            "ix_admin_audit_logs_actor_user_id_sequence",
            "actor_user_id",
            text("sequence DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Strictly increasing, assigned by the database, for the reason the
    # tenant log has one: now() is fixed for the length of a transaction,
    # so rows written in one share a timestamp exactly and a UUID would
    # then decide their order at random. Never exposed; it orders, it
    # does not identify.
    sequence: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        unique=True,
    )

    # Who did it. SET NULL rather than CASCADE, so a staff member who
    # leaves cannot take the record of what they did with them.
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
    )

    # Who they were, copied at the moment they acted, so the row still
    # names somebody after the account is gone. Null only where nobody
    # did it, which on this surface means exactly one thing: the first
    # owner, seeded from the command line before any staff member existed
    # to grant it.
    actor_email: Mapped[str | None] = mapped_column(String(320), default=None)

    action: Mapped[AdminAction] = mapped_column(
        enum_column(AdminAction, name="admin_action"),
    )

    # Nullable, because granting a colleague access is about no
    # workspace. SET NULL, because the row must survive the erasure of
    # the workspace it names -- see this class's docstring, which is the
    # point of the table.
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        default=None,
    )

    # Denormalised on purpose, and the only reason the SET NULL above is
    # survivable: once the id has been nulled, this is what still says
    # which business the entry was about.
    workspace_slug: Mapped[str | None] = mapped_column(String(63), default=None)

    # The other account an action was about: a colleague being promoted,
    # a customer being deactivated. SET NULL for the same reason as the
    # actor -- deleting an account must not edit the record.
    target_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
    )

    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    # Where the request came from, and what it said it was. Both are best
    # effort and neither decides anything -- a header anyone can set, and
    # an address a proxy may have rewritten. They are here because the
    # question this log gets asked after an incident is "was that really
    # them", and an address that does not match the office is the first
    # thing that makes somebody look twice.
    ip_address: Mapped[str | None] = mapped_column(String(45), default=None)
    user_agent: Mapped[str | None] = mapped_column(String(255), default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"AdminAuditLog(id={self.id!r}, action={self.action!r})"
