import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Select,
    Text,
    and_,
    func,
    or_,
    select,
    true,
)
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import LateralFromClause

from app.models.contact import Contact
from app.models.conversation import (
    AiMode,
    Channel,
    Conversation,
    ConversationStatus,
)
from app.models.message import Direction, Message, MessageStatus, SenderType
from app.models.user import User

# How much of the last message an inbox row carries. A row shows one line,
# and WhatsApp allows four thousand characters: sending all of them for
# thirty rows is a preview in name only. Cut in the database rather than in
# Python, so the bytes are never read off the disk or off the wire.
PREVIEW_LENGTH = 160


@dataclass(frozen=True)
class LastMessage:
    """Enough of the newest message to render one line of an inbox."""

    text: str | None
    sender_type: SenderType
    direction: Direction
    status: MessageStatus
    created_at: datetime


@dataclass(frozen=True)
class InboxRow:
    """A conversation with everything needed to draw it beside it.

    The point of the type. An inbox row names a person, says who is
    looking after it and shows what was last said; fetching those three
    per row is the difference between a screen that opens and a screen
    that opens eventually.
    """

    conversation: Conversation
    contact: Contact
    assignee: User | None
    last_message: LastMessage | None


class ConversationRepository:
    """Every query against the conversations table lives here.

    Workspace-scoped throughout, for the reason the contacts repository
    is: an id is not a permission, and a method that will answer without
    a workspace makes the tenant boundary a thing every caller has to
    remember.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        workspace_id: uuid.UUID,
        contact_id: uuid.UUID,
        channel: Channel,
    ) -> Conversation:
        conversation = Conversation(
            workspace_id=workspace_id,
            contact_id=contact_id,
            channel=channel,
        )

        self._session.add(conversation)
        self._session.flush()

        return conversation

    def get(
        self,
        workspace_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> Conversation | None:
        return self._session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.workspace_id == workspace_id,
            )
        )

    def get_row(
        self,
        workspace_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> InboxRow | None:
        """One conversation in the shape the inbox uses.

        The same shape as a row of the list, and deliberately: a client
        that opens a thread, assigns it and closes it should not need a
        second vocabulary for the same object between one screen and the
        next.
        """
        rows = self._session.execute(
            _enriched().where(
                Conversation.workspace_id == workspace_id,
                Conversation.id == conversation_id,
            )
        ).all()

        return _row(rows[0]) if rows else None

    def get_live_for_contact(
        self,
        workspace_id: uuid.UUID,
        contact_id: uuid.UUID,
        channel: Channel,
    ) -> Conversation | None:
        """The contact's thread that is not closed, if they have one.

        There is at most one, enforced by a partial unique index rather
        than by this query being careful. The webhook will reach for this
        on every inbound message.
        """
        return self._session.scalar(
            select(Conversation).where(
                Conversation.workspace_id == workspace_id,
                Conversation.contact_id == contact_id,
                Conversation.channel == channel,
                Conversation.status != ConversationStatus.CLOSED,
            )
        )

    def get_latest_closed_for_contact(
        self,
        workspace_id: uuid.UUID,
        contact_id: uuid.UUID,
        channel: Channel,
    ) -> Conversation | None:
        """The contact's most recently closed thread, if they have one.

        Reached when a customer messages again after a conversation was
        resolved. Reopening the last one keeps their history in one place;
        the alternative is a new thread beside an old one that reads like
        two different customers.
        """
        return self._session.scalar(
            select(Conversation)
            .where(
                Conversation.workspace_id == workspace_id,
                Conversation.contact_id == contact_id,
                Conversation.channel == channel,
                Conversation.status == ConversationStatus.CLOSED,
            )
            .order_by(Conversation.closed_at.desc(), Conversation.id)
            .limit(1)
        )

    def list_for_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
        statuses: Sequence[ConversationStatus] | None = None,
        assigned_user_id: int | None = None,
        contact_id: uuid.UUID | None = None,
        unassigned: bool = False,
        search: str | None = None,
    ) -> Sequence[InboxRow]:
        """One page of the inbox, in one round trip.

        Two joins and a lateral rather than a page of conversations
        followed by a lookup per row for the contact, another for the
        assignee and another for the last message. That is four queries a
        row, thirty rows a page, on the screen the product is opened on.
        """
        rows = self._session.execute(
            self._filtered(
                _enriched(),
                workspace_id,
                statuses,
                assigned_user_id,
                contact_id,
                unassigned,
                search,
            )
            # Most recently active first, which is what an inbox is. A
            # thread with no messages yet sorts last rather than
            # disappearing, and the id breaks ties so pages cannot
            # overlap.
            .order_by(
                Conversation.last_message_at.desc().nullslast(),
                Conversation.created_at.desc(),
                Conversation.id,
            )
            .limit(limit)
            .offset(offset)
        ).all()

        return [_row(row) for row in rows]

    def count_for_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        statuses: Sequence[ConversationStatus] | None = None,
        assigned_user_id: int | None = None,
        contact_id: uuid.UUID | None = None,
        unassigned: bool = False,
        search: str | None = None,
    ) -> int:
        return (
            self._session.scalar(
                self._filtered(
                    # The same contact join the page makes, so that a
                    # search means the same thing to the total as it does
                    # to the rows it is a total of.
                    select(func.count())
                    .select_from(Conversation)
                    .join(Contact, _same_contact()),
                    workspace_id,
                    statuses,
                    assigned_user_id,
                    contact_id,
                    unassigned,
                    search,
                )
            )
            or 0
        )

    @staticmethod
    def _filtered(
        statement: Select[Any],
        workspace_id: uuid.UUID,
        statuses: Sequence[ConversationStatus] | None,
        assigned_user_id: int | None,
        contact_id: uuid.UUID | None,
        unassigned: bool,
        search: str | None,
    ) -> Select[Any]:
        """The filters, applied once to both the page and its count.

        Written in one place because a page and a total that disagree is
        the kind of bug that only shows up as a pagination control that
        promises a page which turns out to be empty.

        A search reads the contact, so both callers join it -- an inner
        join on a foreign key that cannot be null adds no rows and removes
        none. What is shared here is what a search *matches*, which is the
        half that would otherwise drift.
        """
        criteria: list[ColumnElement[bool]] = [
            Conversation.workspace_id == workspace_id
        ]

        if statuses:
            criteria.append(Conversation.status.in_(statuses))

        if unassigned:
            criteria.append(Conversation.assigned_user_id.is_(None))
        elif assigned_user_id is not None:
            criteria.append(Conversation.assigned_user_id == assigned_user_id)

        if contact_id is not None:
            criteria.append(Conversation.contact_id == contact_id)

        if search:
            # Whoever is searching an inbox is looking for a person, not
            # for a thread: they have a name or a number in mind. `ilike`
            # because a search that is case-sensitive looks broken.
            pattern = f"%{search}%"
            criteria.append(
                or_(
                    Contact.name.ilike(pattern),
                    Contact.phone_number.ilike(pattern),
                    Contact.email.ilike(pattern),
                )
            )

        return statement.where(*criteria)

    def set_status(
        self,
        conversation: Conversation,
        status: ConversationStatus,
        *,
        closed_at: datetime | None = None,
        opened_at: datetime | None = None,
    ) -> Conversation:
        conversation.status = status

        # Written together with the status rather than by a separate call,
        # so a conversation cannot be closed without a closing time.
        if closed_at is not None or status != ConversationStatus.CLOSED:
            conversation.closed_at = closed_at

        if opened_at is not None:
            conversation.opened_at = opened_at

        self._session.flush()

        return conversation

    def set_assignee(
        self,
        conversation: Conversation,
        user_id: int | None,
    ) -> Conversation:
        conversation.assigned_user_id = user_id
        self._session.flush()

        return conversation

    def set_ai_mode(self, conversation: Conversation, mode: AiMode) -> Conversation:
        conversation.ai_mode = mode
        self._session.flush()

        return conversation

    def record_activity(
        self,
        conversation: Conversation,
        at: datetime,
        *,
        unread: bool = False,
    ) -> Conversation:
        """Move the conversation to the top of the inbox.

        Denormalised from messages deliberately: the alternative is a
        correlated subquery on every row of every inbox request.

        `unread` is for the customer's messages and not for the team's.
        The count moves by an expression rather than by a number read and
        written back, so two of the customer's messages arriving at once
        are two unread messages and not one -- the row is locked by the
        update, where a read-then-write would let the second overwrite
        the first.
        """
        conversation.last_message_at = at

        if unread:
            conversation.unread_count = Conversation.unread_count + 1

        self._session.flush()

        return conversation

    def take_over(
        self,
        conversation: Conversation,
        *,
        at: datetime,
        reason: str | None,
        user_id: int,
    ) -> Conversation:
        """Put a thread in a person's hands, and switch the assistant off.

        Both in one call, because they are one decision. Written apart,
        the two would eventually be performed apart -- and a conversation
        marked as taken over that the assistant is still answering into is
        the exact failure the plan's business rule exists to prevent.
        """
        conversation.handoff_at = at
        conversation.handoff_reason = reason
        conversation.handoff_by_user_id = user_id
        conversation.ai_mode = AiMode.DISABLED
        self._session.flush()

        return conversation

    def hand_over(
        self,
        conversation: Conversation,
        *,
        at: datetime,
        reason: str | None,
    ) -> Conversation:
        """Mark a thread as needing a person, without claiming it.

        What the assistant does when it cannot answer. The mode is left
        alone, deliberately: a workspace that chose `automatic` chose it,
        and one question the knowledge base could not cover is not grounds
        for silently rewriting that setting. What stops the assistant
        answering the next message is the handoff itself.
        """
        conversation.handoff_at = at
        conversation.handoff_reason = reason
        conversation.handoff_by_user_id = None
        self._session.flush()

        return conversation

    def release(self, conversation: Conversation, mode: AiMode) -> Conversation:
        """Hand a thread back to the assistant.

        Clears the handoff and sets the mode together, for the reason
        `hand_over` sets them together: a thread that still says a human
        has it while the assistant answers into it is the state neither
        the agent nor the customer can make sense of.
        """
        conversation.handoff_at = None
        conversation.handoff_reason = None
        conversation.handoff_by_user_id = None
        conversation.ai_mode = mode
        self._session.flush()

        return conversation

    def mark_read(self, conversation: Conversation, at: datetime) -> Conversation:
        """Say that somebody has looked at this thread.

        A message arriving in the instant between reading the count and
        clearing it is counted as read. It is still at the top of the
        inbox with its text in the row, so what is lost is a badge rather
        than a message, and the alternative -- clearing only up to a
        sequence the client last saw -- is a lock and a round trip for it.
        """
        conversation.unread_count = 0
        conversation.last_read_at = at
        self._session.flush()

        return conversation


def _same_contact() -> ColumnElement[bool]:
    """Both halves of the composite key, not just the contact id.

    The workspace is already filtered, so matching the id alone would
    return the same rows. Naming both is what lets PostgreSQL use the
    unique constraint the foreign key points at, and it keeps the join
    saying the same thing the schema does.
    """
    return and_(
        Contact.workspace_id == Conversation.workspace_id,
        Contact.id == Conversation.contact_id,
    )


def _last_message() -> LateralFromClause:
    """The newest message of each conversation, one row or none.

    A lateral rather than a window function over every message the
    workspace has: it runs for the rows on the page and stops at the first
    match, which the index on (conversation_id, created_at, sequence)
    answers by walking backwards one step.

    `sequence` and not the id breaks the tie, for the reason the thread
    view uses it: now() is fixed for a transaction, so three messages from
    one webhook payload share a created_at, and a UUID sorts at random.
    """
    return (
        select(
            func.left(Message.text_body, PREVIEW_LENGTH, type_=Text).label("text"),
            Message.sender_type.label("sender_type"),
            Message.direction.label("direction"),
            Message.status.label("status"),
            Message.created_at.label("created_at"),
        )
        .where(
            Message.workspace_id == Conversation.workspace_id,
            Message.conversation_id == Conversation.id,
        )
        .order_by(Message.created_at.desc(), Message.sequence.desc())
        .limit(1)
        .lateral("last_message")
    )


def _enriched() -> Select[Any]:
    """The inbox row's query, without its filters.

    The assignee and the last message are outer joins because both are
    ordinarily absent: an unassigned conversation is the normal state of a
    shared inbox, and a thread opened from the dashboard has nothing said
    in it yet.
    """
    preview = _last_message()

    return (
        select(
            Conversation,
            Contact,
            User,
            preview.c.text,
            preview.c.sender_type,
            preview.c.direction,
            preview.c.status,
            preview.c.created_at,
        )
        .join(Contact, _same_contact())
        .outerjoin(User, User.id == Conversation.assigned_user_id)
        .outerjoin(preview, true())
    )


def _row(row: Any) -> InboxRow:
    """One result row of the enriched query, as something with names."""
    (
        conversation,
        contact,
        assignee,
        text,
        sender_type,
        direction,
        status,
        created_at,
    ) = row

    return InboxRow(
        conversation=conversation,
        contact=contact,
        assignee=assignee,
        last_message=(
            None
            if created_at is None
            else LastMessage(
                text=text,
                sender_type=sender_type,
                direction=direction,
                status=status,
                created_at=created_at,
            )
        ),
    )
