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
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column


class AiDecision(StrEnum):
    """What the pipeline did about one customer message."""

    # Sent to the customer. Only reachable in automatic mode.
    ANSWERED = "answered"
    # Drafted and left for a human. Where the plan says pilots start.
    SUGGESTED = "suggested"
    # Deliberately not answered: the assistant did not know, or was not
    # confident enough. A person has to pick this up.
    HANDOFF = "handoff"
    # Not attempted, by configuration -- the conversation has the
    # assistant switched off.
    BLOCKED = "blocked"
    # Attempted and broke. The model erred, or the reply it produced could
    # not be used.
    FAILED = "failed"


class AiResponseLog(Base):
    """One record of the assistant being asked to answer something.

    Written whatever the outcome, including the outcomes where nothing was
    sent, because the question this table answers is "why did the
    assistant do that" -- and the cases worth asking about are mostly the
    ones where it did nothing.

    It holds ids, scores and counts rather than prompts. The plan's own
    instruction is not to keep sensitive prompt contents indefinitely, and
    a table with every customer's message copied into it is a second place
    that data has to be protected, deleted and reasoned about.
    """

    __tablename__ = "ai_response_logs"

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "conversation_id"],
            ["conversations.workspace_id", "conversations.id"],
            ondelete="CASCADE",
            name="fk_ai_response_logs_conversation_in_same_workspace",
        ),
        Index(
            "ix_ai_response_logs_workspace_id_created_at",
            "workspace_id",
            text("created_at DESC"),
        ),
        # Reading one conversation's history of decisions, which is what
        # somebody asking "why did it hand this over" is doing.
        Index("ix_ai_response_logs_conversation_id", "conversation_id"),
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

    # The customer's message this was a response to. Nullable and SET NULL
    # rather than CASCADE: the record of a decision should outlive the
    # message that prompted it, because deleting a message is exactly when
    # somebody wants to know what the assistant did with it.
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"),
        default=None,
    )

    # The reply that was written, when one was. Kept whatever was decided,
    # including for the answers that were withheld: what the assistant
    # would have said is the most useful thing in this table to anyone
    # tuning it. The API returns it only when it is a draft to act on.
    reply_text: Mapped[str | None] = mapped_column(Text, default=None)

    # The message the assistant actually sent, when it sent one. What makes
    # "this customer message has been answered" answerable from one row --
    # and what stops a second run sending a second reply to it.
    sent_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"),
        default=None,
    )

    decision: Mapped[AiDecision] = mapped_column(
        enum_column(AiDecision, name="ai_decision"),
    )

    # Why, in a word: `no_knowledge`, `low_confidence`, `ai_disabled`,
    # `provider_error`. Free text rather than an enum because this is
    # diagnostics, and a vocabulary that needs a migration every time
    # somebody wants to distinguish two failures is one nobody extends.
    reason: Mapped[str | None] = mapped_column(String(50), default=None)

    model: Mapped[str | None] = mapped_column(String(100), default=None)

    # Which version of the instructions produced this. The plan asks for
    # it, and the reason is evaluation: without it, a change in answer
    # quality cannot be attributed to a change in the prompt.
    prompt_version: Mapped[str] = mapped_column(String(20))

    # What was actually searched for, which is not always the customer's
    # words, and the chunks that came back. Both are what makes an answer
    # reproducible: the same query against the same chunks should produce
    # the same evidence.
    retrieval_query: Mapped[str | None] = mapped_column(Text, default=None)

    retrieved_chunk_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(Uuid),
        default=list,
        server_default=text("'{}'::uuid[]"),
    )

    confidence: Mapped[float | None] = mapped_column(default=None)

    latency_ms: Mapped[int | None] = mapped_column(default=None)

    input_tokens: Mapped[int | None] = mapped_column(default=None)

    output_tokens: Mapped[int | None] = mapped_column(default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"AiResponseLog(id={self.id!r}, decision={self.decision!r}, "
            f"conversation_id={self.conversation_id!r})"
        )
