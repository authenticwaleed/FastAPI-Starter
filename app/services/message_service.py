import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.exceptions import ConversationClosedError
from app.db.session import SessionDep
from app.models.conversation import Conversation
from app.models.message import Direction, Message, MessageStatus, SenderType
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.schemas.message import MessageCreate
from app.services.conversation_service import (
    ConversationRepositoryDep,
    ConversationService,
    ConversationServiceDep,
)
from app.services.workspace_service import WorkspaceAccess


class MessageService:
    """What is in a thread, and adding to it.

    Reaching a conversation goes through ConversationService, so a
    message can only ever be written to a thread whose workspace has
    already been established -- and the composite foreign key underneath
    means the database would refuse it even if that were skipped.
    """

    def __init__(
        self,
        session: Session,
        messages: MessageRepository,
        conversations: ConversationRepository,
        conversation_service: ConversationService,
    ) -> None:
        self._session = session
        self._messages = messages
        self._conversations = conversations
        self._conversation_service = conversation_service

    def list_for(
        self,
        access: WorkspaceAccess,
        conversation_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 30,
    ) -> tuple[Sequence[Message], int]:
        conversation = self._conversation_service.get(access, conversation_id)
        workspace_id = access.workspace.id

        messages = self._messages.list_for_conversation(
            workspace_id,
            conversation.id,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        total = self._messages.count_for_conversation(workspace_id, conversation.id)

        return messages, total

    def send(
        self,
        access: WorkspaceAccess,
        conversation_id: uuid.UUID,
        payload: MessageCreate,
    ) -> Message:
        """Record an agent's reply.

        `queued` and not `sent`, because nothing sends it. There is no
        provider connected yet, and a message marked sent that never left
        the building is the kind of lie an inbox never recovers from --
        the agent believes the customer was answered. The next phase is
        what moves these to sent and then delivered.
        """
        conversation = self._conversation_service.get(access, conversation_id)

        if conversation.is_closed:
            raise ConversationClosedError(conversation.id)

        message = self._messages.create(
            workspace_id=access.workspace.id,
            conversation_id=conversation.id,
            sender_type=SenderType.AGENT,
            direction=Direction.OUTBOUND,
            channel=conversation.channel,
            status=MessageStatus.QUEUED,
            text=payload.text,
        )

        self._touch(conversation, message)
        self._session.commit()

        return message

    def _touch(self, conversation: Conversation, message: Message) -> None:
        """Keep the inbox ordering honest.

        Written in the same transaction as the message, so a thread cannot
        exist with a reply in it and a last_message_at that predates it.
        """
        self._conversations.record_activity(
            conversation,
            message.created_at or datetime.now(UTC),
        )


def get_message_repository(session: SessionDep) -> MessageRepository:
    return MessageRepository(session)


MessageRepositoryDep = Annotated[MessageRepository, Depends(get_message_repository)]


def get_message_service(
    session: SessionDep,
    messages: MessageRepositoryDep,
    conversations: ConversationRepositoryDep,
    conversation_service: ConversationServiceDep,
) -> MessageService:
    return MessageService(
        session=session,
        messages=messages,
        conversations=conversations,
        conversation_service=conversation_service,
    )


MessageServiceDep = Annotated[MessageService, Depends(get_message_service)]
