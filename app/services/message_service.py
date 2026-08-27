import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ContactNotFoundError,
    ConversationClosedError,
    MessagingProviderError,
)
from app.db.session import SessionDep
from app.models.conversation import Conversation
from app.models.message import Direction, Message, MessageStatus, SenderType
from app.repositories.contact_repository import ContactRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.whatsapp_account_repository import (
    WhatsAppAccountRepository,
)
from app.schemas.message import MessageCreate
from app.services.contact_service import ContactRepositoryDep
from app.services.conversation_service import (
    ConversationRepositoryDep,
    ConversationService,
    ConversationServiceDep,
)
from app.services.whatsapp_service import (
    WhatsAppAccountRepositoryDep,
    WhatsAppService,
    WhatsAppServiceDep,
)
from app.services.workspace_service import WorkspaceAccess

logger = logging.getLogger(__name__)


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
        contacts: ContactRepository,
        accounts: WhatsAppAccountRepository,
        conversation_service: ConversationService,
        whatsapp: WhatsAppService,
    ) -> None:
        self._session = session
        self._messages = messages
        self._conversations = conversations
        self._contacts = contacts
        self._accounts = accounts
        self._conversation_service = conversation_service
        self._whatsapp = whatsapp

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
        """Record an agent's reply, then try to deliver it.

        Written and committed before the provider is called, and
        deliberately in that order. A crash, a timeout or a restart
        between the two loses the delivery, which the provider's own
        retries and a human can recover from; the other order loses the
        message, and nobody can tell that it existed.

        A workspace with no number connected leaves the message `queued`.
        Nothing drains that queue yet -- a retry worker is a later phase --
        but a reply that is stored and undelivered is recoverable, where a
        refusal at this point would make the inbox unusable for a business
        that is still being set up.
        """
        conversation = self._conversation_service.get(access, conversation_id)

        if conversation.is_closed:
            raise ConversationClosedError(conversation.id)

        workspace_id = access.workspace.id

        message = self._messages.create(
            workspace_id=workspace_id,
            conversation_id=conversation.id,
            sender_type=SenderType.AGENT,
            direction=Direction.OUTBOUND,
            channel=conversation.channel,
            status=MessageStatus.QUEUED,
            text=payload.text,
        )

        self._touch(conversation, message)
        self._session.commit()

        account = self._accounts.get_for_workspace(workspace_id)

        if account is None:
            return message

        contact = self._contacts.get(workspace_id, conversation.contact_id)

        if contact is None:
            # The composite foreign key makes this unreachable. It is
            # here because "unreachable" and "unchecked" look identical
            # from the next person's chair.
            raise ContactNotFoundError(workspace_id, conversation.contact_id)

        try:
            sent = self._whatsapp.deliver(
                account,
                to=contact.phone_number,
                text=payload.text,
            )
        except MessagingProviderError:
            # Recorded on the message and then re-raised. The agent is
            # told it failed, and the thread shows why rather than showing
            # a reply that looks like it went.
            message.status = MessageStatus.FAILED
            self._session.commit()
            raise

        message.status = MessageStatus.SENT
        message.external_message_id = sent.external_message_id
        message.sent_at = datetime.now(UTC)
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
    contacts: ContactRepositoryDep,
    accounts: WhatsAppAccountRepositoryDep,
    conversation_service: ConversationServiceDep,
    whatsapp: WhatsAppServiceDep,
) -> MessageService:
    return MessageService(
        session=session,
        messages=messages,
        conversations=conversations,
        contacts=contacts,
        accounts=accounts,
        conversation_service=conversation_service,
        whatsapp=whatsapp,
    )


MessageServiceDep = Annotated[MessageService, Depends(get_message_service)]
