import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.conversation import Channel
from app.models.message import (
    ContentType,
    Direction,
    Message,
    MessageStatus,
    SenderType,
)


class MessageRepository:
    """Every query against the messages table lives here."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        workspace_id: uuid.UUID,
        conversation_id: uuid.UUID,
        sender_type: SenderType,
        direction: Direction,
        channel: Channel,
        status: MessageStatus,
        text: str | None = None,
        content_type: ContentType = ContentType.TEXT,
        external_message_id: str | None = None,
        sent_at: datetime | None = None,
        received_at: datetime | None = None,
    ) -> Message:
        message = Message(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            sender_type=sender_type,
            direction=direction,
            channel=channel,
            status=status,
            text_body=text,
            content_type=content_type,
            external_message_id=external_message_id,
            sent_at=sent_at,
            received_at=received_at,
        )

        self._session.add(message)
        # Flush so the database assigns the id and the sequence, which is
        # what the caller needs in order to order what it just wrote.
        self._session.flush()

        return message

    def list_for_conversation(
        self,
        workspace_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
    ) -> Sequence[Message]:
        """One page of a thread, most recent first.

        `sequence` and not the id breaks the tie. now() is fixed for a
        transaction, so a webhook writing three messages from one payload
        gives all three the same created_at -- and a UUID sorts at random,
        which would render that thread in a different order every time it
        was read.
        """
        return self._session.scalars(
            select(Message)
            .where(
                Message.workspace_id == workspace_id,
                Message.conversation_id == conversation_id,
            )
            .order_by(Message.created_at.desc(), Message.sequence.desc())
            .limit(limit)
            .offset(offset)
        ).all()

    def count_for_conversation(
        self,
        workspace_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> int:
        return (
            self._session.scalar(
                select(func.count())
                .select_from(Message)
                .where(
                    Message.workspace_id == workspace_id,
                    Message.conversation_id == conversation_id,
                )
            )
            or 0
        )

    def get_by_external_id(
        self,
        workspace_id: uuid.UUID,
        external_message_id: str,
    ) -> Message | None:
        """What makes webhook delivery idempotent.

        A provider retries. Finding the row already written is how a retry
        stops being a duplicate message in somebody's inbox.
        """
        return self._session.scalar(
            select(Message).where(
                Message.workspace_id == workspace_id,
                Message.external_message_id == external_message_id,
            )
        )
