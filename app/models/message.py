import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column
from app.models.conversation import Channel


class SenderType(StrEnum):
    CUSTOMER = "customer"
    AGENT = "agent"
    AI = "ai"
    # Not a person: "this conversation was closed", "the assistant handed
    # over". Nothing writes one yet.
    SYSTEM = "system"


class Direction(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageStatus(StrEnum):
    # An outbound message that exists but has not been handed to a
    # provider. Everything this API sends is queued and stays queued:
    # there is nothing delivering yet, which is the next phase.
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    # What an inbound message is. It did not go anywhere; it arrived.
    RECEIVED = "received"


class ContentType(StrEnum):
    """What kind of thing a message carries.

    Text, and only text. The plan lists images, audio, documents and
    interactive templates as later support and says outright not to build
    every WhatsApp type into the MVP, so this is the one that matters and
    the enum is what makes adding the rest a deliberate migration.
    """

    TEXT = "text"


class Message(Base):
    """One message in one conversation."""

    __tablename__ = "messages"

    __table_args__ = (
        # The workspace comes from the conversation, and the database is
        # what enforces that rather than every caller remembering to. A
        # message physically cannot name a conversation in a different
        # workspace.
        ForeignKeyConstraint(
            ["workspace_id", "conversation_id"],
            ["conversations.workspace_id", "conversations.id"],
            ondelete="CASCADE",
            name="fk_messages_conversation_in_same_workspace",
        ),
        # The provider's own id for this message, which is what makes
        # webhook delivery idempotent: a retried notification finds the
        # row already there instead of writing a second copy. Per
        # workspace, since two businesses' providers know nothing of each
        # other. NULLs are distinct in PostgreSQL, so the messages this
        # API originates -- which have no provider id yet -- do not
        # collide with each other.
        UniqueConstraint(
            "workspace_id",
            "external_message_id",
            name="uq_messages_workspace_id_external_message_id",
        ),
        # Reading a thread: one conversation, in order. `sequence` rather
        # than the id breaks the tie -- see the column below.
        Index(
            "ix_messages_conversation_id_created_at",
            "conversation_id",
            "created_at",
            "sequence",
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
    # now() is fixed for a transaction -- so a webhook delivering three
    # messages in one payload would write three rows sharing a timestamp
    # and a thread would render in a random order. Never exposed; it
    # orders, it does not identify.
    sequence: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        unique=True,
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )

    conversation_id: Mapped[uuid.UUID]

    sender_type: Mapped[SenderType] = mapped_column(
        enum_column(SenderType, name="message_sender_type"),
    )

    direction: Mapped[Direction] = mapped_column(
        enum_column(Direction, name="message_direction"),
    )

    channel: Mapped[Channel] = mapped_column(
        enum_column(Channel, name="message_channel"),
        default=Channel.WHATSAPP,
        server_default=text("'whatsapp'"),
    )

    external_message_id: Mapped[str | None] = mapped_column(
        String(255),
        default=None,
    )

    content_type: Mapped[ContentType] = mapped_column(
        enum_column(ContentType, name="message_content_type"),
        default=ContentType.TEXT,
        server_default=text("'text'"),
    )

    # Unbounded, because a customer pasting an address or an order history
    # into WhatsApp is ordinary and a truncated message is worse than a
    # long one. Nullable for the media types that do not have text.
    text_body: Mapped[str | None] = mapped_column("text", Text, default=None)

    status: Mapped[MessageStatus] = mapped_column(
        enum_column(MessageStatus, name="message_status"),
    )

    # The provider's timestamps, not this database's: when it actually
    # left, and when it actually arrived. Both null until there is a
    # provider to tell us, which is why `created_at` is what ordering
    # uses.
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

    received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"Message(id={self.id!r}, direction={self.direction!r}, "
            f"sender_type={self.sender_type!r})"
        )
