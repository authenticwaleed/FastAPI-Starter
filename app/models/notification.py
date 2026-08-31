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
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column


class NotificationKind(StrEnum):
    """What a notification is telling somebody.

    Two shapes, and the difference decides whether one can repeat. The
    first three are about a *thing that happened* -- this thread, this
    document -- and two of them are two events worth seeing separately.
    The last is about a *condition*: an integration that is not working
    is not more broken for having failed twice, and a second unread alert
    saying so adds nothing but noise. See `dedupe_key` below.
    """

    CONVERSATION_ASSIGNED = "conversation_assigned"
    HANDOFF_REQUESTED = "handoff_requested"
    KNOWLEDGE_INGESTION_FAILED = "knowledge_ingestion_failed"
    MESSAGE_DELIVERY_FAILED = "message_delivery_failed"
    BILLING_PAYMENT_FAILED = "billing_payment_failed"


class Notification(Base):
    """One thing one person is being told, about one workspace.

    Addressed to a user rather than to a workspace, which is what makes
    `/api/v1/notifications` sensible without a workspace in its path: a
    person opens their notifications and sees everything meant for them,
    from every business they work in. It is also why the workspace is a
    column -- somebody who works in three needs to know which one this is
    about.

    One row per recipient. A handoff that eight agents should see is
    eight rows, because read state is per person and the endpoints this
    phase asks for -- an unread count, marking one read, marking all read
    -- are all per person. A shared row would need a second table to hold
    who had read it, which is the same rows in a worse shape.

    Self-describing, deliberately. The title and body are composed when
    the thing happens and never recomputed, so a notification is a record
    of what was true at a moment rather than a live view that quietly
    rewrites itself. `metadata` carries the ids a client needs to link
    somewhere, which is a different job.
    """

    __tablename__ = "notifications"

    __table_args__ = (
        # The feed, and the count, in one shape: this person's, newest
        # first. Both endpoints filter on the recipient before anything
        # else, so the user leads.
        Index(
            "ix_notifications_user_id_created_at",
            "user_id",
            text("created_at DESC"),
            text("sequence DESC"),
        ),
        # "Do not tell them the same thing twice while they still have
        # not read it the first time." A partial unique index rather than
        # a check in the service, for the reason every other rule of this
        # kind here is one: a check is something a second caller can race,
        # and an index is not.
        #
        # NULLs are distinct in PostgreSQL, so the notifications that are
        # about a specific event -- and should repeat -- simply leave the
        # key null and never collide.
        Index(
            "uq_notifications_user_id_dedupe_key_unread",
            "user_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("read_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    # Strictly increasing, assigned by the database, and the reason this
    # column exists rather than ordering by the id: a UUID sorts at
    # random, and `created_at` alone is not enough because PostgreSQL's
    # now() is fixed for a transaction -- so a handoff told to eight
    # agents writes eight rows sharing a timestamp, and two things
    # happening in one request would render in a random order. The same
    # column messages carry, for the same reason. Never exposed; it
    # orders, it does not identify.
    sequence: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        unique=True,
    )

    # Who is being told. Cascades, because a notification for a deleted
    # account is addressed to nobody.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    # Which business it is about. Cascades for the same reason: a
    # workspace that is gone has nothing left to notify anybody about.
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )

    kind: Mapped[NotificationKind] = mapped_column(
        enum_column(NotificationKind, name="notification_kind"),
    )

    title: Mapped[str] = mapped_column(String(200))

    body: Mapped[str | None] = mapped_column(Text, default=None)

    # Set only by the kinds that are about a condition rather than an
    # event. See NotificationKind, and the partial index above.
    dedupe_key: Mapped[str | None] = mapped_column(String(120), default=None)

    # Whatever a client needs to link somewhere: a conversation id, a
    # document id. Not what the notification *says* -- that is the title
    # and the body, composed once and left alone.
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    # Null until read. A timestamp rather than a flag, for the reason
    # `email_verified_at` is one: "when did they see this" is a question
    # somebody asks, and a boolean cannot answer it.
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"Notification(id={self.id!r}, kind={self.kind!r})"
