from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.conversation import Channel
from app.models.message import (
    ContentType,
    Direction,
    MessageStatus,
    SenderType,
)


class MessageCreate(BaseModel):
    """An agent's reply.

    Only text, because only text is what the MVP sends. 4096 is
    WhatsApp's own limit for a text body, so a longer one would be
    accepted here and refused by the provider later, which is the worst
    place to find out.
    """

    text: Annotated[str, Field(min_length=1, max_length=4096)]


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    sender_type: SenderType
    direction: Direction
    channel: Channel
    content_type: ContentType
    # Reads the model's `text_body`, which carries the column the plan
    # calls `text`: `text` is also SQLAlchemy's type constructor, and a
    # column attribute called that reads like a mistake in every model
    # that imports it.
    text: str | None = Field(validation_alias="text_body")
    status: MessageStatus
    sent_at: datetime | None
    received_at: datetime | None
    created_at: datetime


class MessagePage(BaseModel):
    """One page of a thread, most recent first.

    That order is what a chat screen opens with: page one is what you see,
    and paging back is scrolling up. A client rendering top to bottom
    reverses each page.
    """

    items: list[MessageRead]
    total: int
    page: int
    page_size: int
