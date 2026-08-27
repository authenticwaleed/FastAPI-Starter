import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column


class Channel(StrEnum):
    """Where a conversation happens.

    One value, because the product reaches people on WhatsApp and adding
    the others before that works would be building for an audience it does
    not have yet. It is an enum rather than a bare string so that adding
    Instagram is a migration somebody writes on purpose.
    """

    WHATSAPP = "whatsapp"


class ConversationStatus(StrEnum):
    OPEN = "open"
    # Waiting on somebody -- the customer, a delivery, a decision. What it
    # means precisely is for the product to settle; what matters here is
    # that it is not closed, so it still holds the contact's open thread.
    PENDING = "pending"
    CLOSED = "closed"


class AiMode(StrEnum):
    """How much the assistant may do in this conversation.

    Nothing reads this yet. It is here because the column belongs to the
    conversation rather than to the AI, and adding it now means the
    pilots' setting exists before there is an assistant to configure.
    """

    DISABLED = "disabled"
    # Draft a reply for a human to approve. Where the plan says pilots
    # should start, and so the default.
    SUGGEST_ONLY = "suggest_only"
    AUTOMATIC = "automatic"


class ConversationState(StrEnum):
    """Who is answering this thread, derived rather than stored.

    Derived on purpose. It is a reading of `handoff_at` and `ai_mode`
    together, and storing it would be a third field that has to be kept
    consistent with the two it is computed from -- which is the kind of
    thing that is right on the day it is written and wrong a month later.
    """

    AI_ACTIVE = "ai_active"
    SUGGEST_ONLY = "suggest_only"
    HUMAN_ACTIVE = "human_active"
    AI_DISABLED = "ai_disabled"


class Conversation(Base):
    """One thread between a business and one of its customers."""

    __tablename__ = "conversations"

    __table_args__ = (
        # The target of the composite foreign key on messages. Redundant
        # with the primary key as an index, and not redundant as a
        # constraint: it is what lets another table say "this row, in this
        # workspace" rather than "this row, and trust me about the
        # workspace".
        UniqueConstraint("workspace_id", "id", name="uq_conversations_workspace_id_id"),
        # A contact belongs to a workspace, and so does this conversation.
        # Pointing at both columns together means the database refuses a
        # conversation that reaches across the boundary -- rather than the
        # application refusing it, correctly, every time somebody
        # remembers to.
        ForeignKeyConstraint(
            ["workspace_id", "contact_id"],
            ["contacts.workspace_id", "contacts.id"],
            ondelete="CASCADE",
            name="fk_conversations_contact_in_same_workspace",
        ),
        # One live thread per person per channel. Without this, two agents
        # opening a conversation with the same customer at the same moment
        # produce two threads, and half the history goes to each. Partial,
        # so that closed conversations accumulate as history without
        # blocking the next one.
        Index(
            "uq_conversations_one_open_per_contact",
            "workspace_id",
            "contact_id",
            "channel",
            unique=True,
            postgresql_where=text("status <> 'closed'"),
        ),
        # The shape the inbox asks for: one workspace's conversations,
        # most recently active first.
        #
        # Every column of the sort, in the sort's own direction, including
        # `NULLS LAST` and both tie-breakers. That is not tidiness. An
        # index that orders even slightly differently cannot be used to
        # order by, so PostgreSQL joins the workspace's entire history to
        # its contacts and its last messages, sorts all of it, and returns
        # thirty rows -- measured at half a second for twenty thousand
        # conversations, against one millisecond for this.
        Index(
            "ix_conversations_inbox_order",
            "workspace_id",
            text("last_message_at DESC NULLS LAST"),
            text("created_at DESC"),
            "id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )

    contact_id: Mapped[uuid.UUID]

    channel: Mapped[Channel] = mapped_column(
        enum_column(Channel, name="conversation_channel"),
        default=Channel.WHATSAPP,
        server_default=text("'whatsapp'"),
    )

    status: Mapped[ConversationStatus] = mapped_column(
        enum_column(ConversationStatus, name="conversation_status"),
        default=ConversationStatus.OPEN,
        server_default=text("'open'"),
    )

    # Who is looking after this thread. Nullable: an unassigned
    # conversation is the normal state of a shared inbox, not an error.
    # SET NULL rather than CASCADE, because somebody leaving must not take
    # a customer's conversation with them.
    assigned_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
    )

    ai_mode: Mapped[AiMode] = mapped_column(
        enum_column(AiMode, name="conversation_ai_mode"),
        default=AiMode.SUGGEST_ONLY,
        server_default=text("'suggest_only'"),
    )

    # Denormalised from messages on purpose. An inbox sorts by it on every
    # request, and computing it from a join would make the cheapest screen
    # in the product the most expensive query in it.
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

    # How many of the customer's messages nobody has looked at yet.
    #
    # A property of the conversation rather than of a person reading it:
    # this is a shared inbox, and a queue where a thread a colleague has
    # already answered still shows a badge on everybody else's screen is a
    # queue that gets worked twice. Per-agent read state is another table
    # and a join on every row, and it buys something a small team does not
    # want.
    #
    # Denormalised for the reason last_message_at is. The alternative is
    # counting messages since a timestamp on every row of every request.
    unread_count: Mapped[int] = mapped_column(
        default=0,
        server_default=text("0"),
    )

    # When a person took this thread over, if one has. The pair with
    # ai_mode is deliberate and they answer different questions: ai_mode
    # is what the assistant is permitted to do, this is whether a human
    # has stepped in. A thread can be assigned to an agent with the
    # assistant still drafting, and that is a normal state rather than a
    # contradiction.
    handoff_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

    # Why it is with a person. Either the assistant's own short code --
    # `no_knowledge`, `low_confidence` -- or whatever the agent typed.
    handoff_reason: Mapped[str | None] = mapped_column(String(200), default=None)

    # Who took it. Null while a thread is handed over by the assistant and
    # nobody has claimed it yet, which is the state a shared inbox spends
    # most of its time in.
    handoff_by_user_id: Mapped[int | None] = mapped_column(
        # Named, unlike the assignee's key above, because this one is
        # added by a migration rather than created with the table -- and
        # an unnamed constraint is one no downgrade can drop.
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
            name="fk_conversations_handoff_by_user_id_users",
        ),
        default=None,
    )

    # When somebody last said they had read this. Not what the count is
    # derived from -- the count is its own column -- but what makes it
    # explicable afterwards, and what a rebuild would work from if the two
    # ever drifted apart.
    last_read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

    # When the current open period began, which reopening restarts. The
    # pair with closed_at is what "how long was this open for" is measured
    # from.
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
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

    @property
    def is_closed(self) -> bool:
        return self.status == ConversationStatus.CLOSED

    @property
    def is_with_a_human(self) -> bool:
        return self.handoff_at is not None

    @property
    def state(self) -> "ConversationState":
        """Who is answering, as one value a dashboard can render.

        The plan names three states; there are four, because "switched
        off" and "a person took it" are different situations with
        different fixes -- one is a setting somebody changed, the other is
        a colleague working. A human having the thread outranks the mode,
        since taking over is precisely the act of overriding it.
        """
        if self.is_with_a_human:
            return ConversationState.HUMAN_ACTIVE

        if self.ai_mode == AiMode.AUTOMATIC:
            return ConversationState.AI_ACTIVE

        if self.ai_mode == AiMode.SUGGEST_ONLY:
            return ConversationState.SUGGEST_ONLY

        return ConversationState.AI_DISABLED

    def __repr__(self) -> str:
        return f"Conversation(id={self.id!r}, status={self.status!r})"
