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
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column


class EventType(StrEnum):
    """Something that changed who is looking after a conversation.

    Only the events about control. Assigning, closing and reopening are
    recorded on the conversation itself as state, and duplicating them
    here would make this a second, slower copy of the same facts. What is
    here is what has no other home: the passing of a thread between the
    assistant and a person.
    """

    # The assistant declined and left it for somebody: it did not know,
    # or was not sure enough, or the model was unavailable.
    AI_HANDOFF = "ai_handoff"
    # A person took it. The assistant stops answering until released.
    HUMAN_TAKEOVER = "human_takeover"
    # A person handed it back.
    AI_RELEASED = "ai_released"


class ConversationEvent(Base):
    """The audit trail for who had a conversation, and why.

    A table rather than columns because the question is historical. The
    conversation's own `handoff_at` says who has it now; "how often does
    the assistant give up on this customer" and "how many threads did we
    take over last week" are questions about a sequence, and a column that
    is overwritten each time cannot answer them.
    """

    __tablename__ = "conversation_events"

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "conversation_id"],
            ["conversations.workspace_id", "conversations.id"],
            ondelete="CASCADE",
            name="fk_conversation_events_conversation_in_same_workspace",
        ),
        # Reading one thread's history, which is what an agent asking
        # "why is this mine" is doing.
        Index(
            "ix_conversation_events_conversation_id_created_at",
            "conversation_id",
            text("created_at DESC"),
        ),
        # Counting a workspace's handoffs over a period, which is what the
        # analytics ask for.
        Index(
            "ix_conversation_events_workspace_id_created_at",
            "workspace_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )

    # Strictly increasing, assigned by the database, and the reason this
    # column exists rather than ordering by created_at and the id: now()
    # is fixed for a transaction, so two rows written in one give the same
    # timestamp -- and a UUID breaks that tie at random. Never exposed; it
    # orders, it does not identify.
    sequence: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        unique=True,
    )

    conversation_id: Mapped[uuid.UUID]

    event_type: Mapped[EventType] = mapped_column(
        enum_column(EventType, name="conversation_event_type"),
    )

    # Who did it. Null means the assistant did: it is the only actor here
    # that is not a person, and giving it a fake user id would put a row
    # in the audit trail that names somebody who did nothing.
    actor_user_id: Mapped[int | None] = mapped_column(
        # SET NULL rather than CASCADE, for the reason assignment uses it:
        # somebody leaving must not delete the record of what they did.
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
    )

    # Why, in a few words. The assistant's own reasons are the short codes
    # it records against a decision -- `no_knowledge`, `low_confidence`;
    # a person's is whatever they typed, or nothing.
    reason: Mapped[str | None] = mapped_column(String(200), default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"ConversationEvent(id={self.id!r}, event_type={self.event_type!r}, "
            f"conversation_id={self.conversation_id!r})"
        )
