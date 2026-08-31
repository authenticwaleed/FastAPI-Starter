from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.notification import NotificationKind


class NotificationRead(BaseModel):
    """One thing somebody is being told."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: NotificationKind
    # Which business this is about. Always present, because a person who
    # works in three needs to know which one a notification came from --
    # and these endpoints have no workspace in their path.
    workspace_id: UUID
    title: str
    body: str | None
    # Ids a client can link on: a conversation, a document. Not what the
    # notification says -- that is the title and body, written when the
    # thing happened and never recomputed.
    metadata: dict[str, Any] = Field(validation_alias="meta")
    read_at: datetime | None
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationRead]
    total: int
    page: int
    page_size: int


class UnreadCount(BaseModel):
    """What a badge shows.

    Its own endpoint rather than a field on the list, because a client
    polls this far more often than it opens the feed -- and a count is
    one query where a page is two.
    """

    unread: int


class MarkedRead(BaseModel):
    """How many the last call cleared.

    Worth returning: a client that has been showing a stale badge learns
    it was stale, and a call that cleared nothing is visibly different
    from one that cleared forty.
    """

    marked_read: int
