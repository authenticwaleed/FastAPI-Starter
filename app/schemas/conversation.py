from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.contact import ContactStatus
from app.models.conversation import (
    AiMode,
    Channel,
    ConversationState,
    ConversationStatus,
)
from app.models.conversation_event import EventType
from app.models.message import Direction, MessageStatus, SenderType


class ConversationCreate(BaseModel):
    """Open a thread with a contact.

    The contact is named, not described: a conversation is always with
    somebody the workspace already knows, and creating a contact by
    side effect here would be a second, quieter path into the contacts
    table with none of its rules.
    """

    contact_id: UUID
    channel: Channel = Channel.WHATSAPP


class ConversationUpdate(BaseModel):
    """A partial update. An omitted field means "leave this alone".

    `status` accepts `closed` and `open` as well as `pending`, and setting
    it does exactly what the `/close` and `/reopen` endpoints do -- they
    call the same code. Two ways to say a thing is fine; two
    implementations of it are what let the timestamps drift apart.
    """

    status: ConversationStatus | None = None
    ai_mode: AiMode | None = None


class ConversationAssign(BaseModel):
    """Hand a thread to somebody, or to nobody.

    An explicit null unassigns, which is why this is a body rather than a
    path: `DELETE .../assign` would be a second endpoint for what is one
    decision with two outcomes.
    """

    user_id: int | None = None


class ContactSummary(BaseModel):
    """Who the thread is with, as much as an inbox row shows of them.

    Not the contact record: their email, their source, whatever the
    business has stored about them in `metadata` are a profile, and the
    profile has its own endpoint. This is a name, a number and a badge.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str | None
    phone_number: str
    status: ContactStatus


class AssigneeSummary(BaseModel):
    """The colleague looking after a thread.

    The name is here because "assigned to 41" is not something to put in
    front of anyone, and the email because two people called Ali is a
    normal thing for a team to contain.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: EmailStr


class MessagePreview(BaseModel):
    """The last thing said, as one line.

    `text` is truncated -- an inbox row shows a line, and the thread
    endpoint is where the whole message is. `sender_type` is what tells
    a row whether the business is waiting on the customer or the customer
    is waiting on the business, which is the thing an agent scans for.
    """

    model_config = ConfigDict(from_attributes=True)

    text: str | None
    sender_type: SenderType
    direction: Direction
    status: MessageStatus
    created_at: datetime


class ConversationTakeover(BaseModel):
    """Take a thread over from the assistant.

    The reason is optional and worth asking for: "customer is angry",
    "refund", "asked for a person". It is what makes the audit trail
    readable a month later, when the question is which kinds of
    conversation the assistant keeps failing at.
    """

    reason: Annotated[str, Field(min_length=1, max_length=200)] | None = None


class ConversationRelease(BaseModel):
    """Hand a thread back to the assistant.

    Defaults to drafting rather than to answering: a thread somebody had
    to take over is not the one to put back on full automation without
    saying so. Nothing remembers what the mode was before -- a stored
    "previous mode" would be another field to keep true, and the safe
    value is a better default than a remembered one.
    """

    ai_mode: AiMode = AiMode.SUGGEST_ONLY


class ConversationEventRead(BaseModel):
    """One entry in a thread's handoff history."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: EventType
    # Null means the assistant did it: it is the only actor here that is
    # not a person.
    actor_user_id: int | None
    reason: str | None
    created_at: datetime


class ConversationEventPage(BaseModel):
    items: list[ConversationEventRead]
    total: int
    page: int
    page_size: int


class ConversationRead(BaseModel):
    """One conversation, with everything needed to render it.

    The contact, the assignee and the last message are embedded rather
    than referenced. A row of an inbox names a person, says who has it and
    shows what was last said, and a client that has to ask for those
    separately makes four requests per row of a screen that has thirty.

    The same shape comes back from every conversation endpoint, including
    the ones that change something, so a client can redraw the row from
    the response it already has.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contact: ContactSummary
    channel: Channel
    status: ConversationStatus
    assigned_user: AssigneeSummary | None
    ai_mode: AiMode
    # Who is answering, as one value: `ai_active`, `suggest_only`,
    # `human_active` or `ai_disabled`. Derived from `ai_mode` and the
    # handoff below, so a dashboard has one field to render rather than a
    # rule to reimplement.
    state: ConversationState
    handoff_at: datetime | None
    handoff_reason: str | None
    # Who took it. Null with `handoff_at` set means the assistant handed
    # it over and nobody has claimed it yet.
    handoff_by_user_id: int | None
    last_message: MessagePreview | None
    last_message_at: datetime | None
    unread_count: int
    last_read_at: datetime | None
    opened_at: datetime
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ConversationPage(BaseModel):
    items: list[ConversationRead]
    total: int
    page: int
    page_size: int
