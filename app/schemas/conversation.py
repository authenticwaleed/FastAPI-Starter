from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.conversation import AiMode, Channel, ConversationStatus


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


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contact_id: UUID
    channel: Channel
    status: ConversationStatus
    assigned_user_id: int | None
    ai_mode: AiMode
    last_message_at: datetime | None
    opened_at: datetime
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ConversationPage(BaseModel):
    items: list[ConversationRead]
    total: int
    page: int
    page_size: int
