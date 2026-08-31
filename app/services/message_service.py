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
    ConversationNotFoundError,
    MessagingProviderError,
)
from app.db.session import SessionDep
from app.models.conversation import Conversation
from app.models.message import Direction, Message, MessageStatus, SenderType
from app.models.notification import NotificationKind
from app.models.workspace import Workspace
from app.repositories.contact_repository import ContactRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.whatsapp_account_repository import (
    WhatsAppAccountRepository,
)
from app.schemas.message import MessageCreate
from app.services.contact_service import ContactRepositoryDep
from app.services.conversation_service import ConversationRepositoryDep
from app.services.notification_service import (
    NotificationService,
    NotificationServiceDep,
)
from app.services.whatsapp_service import (
    WhatsAppAccountRepositoryDep,
    WhatsAppService,
    WhatsAppServiceDep,
)
from app.services.workspace_service import MAY_ADMINISTER

logger = logging.getLogger(__name__)


class MessageService:
    """What is in a thread, and adding to it.

    Scoped to a workspace rather than to a caller's membership. Everything
    here needs to know which business a message belongs to and nothing
    here needs to know who asked -- and the difference matters, because
    the assistant answering a webhook is not a member of anything. The
    route proves the caller may act before handing the workspace over;
    the composite foreign key underneath means the database would refuse a
    cross-tenant write even if that were skipped.
    """

    def __init__(
        self,
        session: Session,
        messages: MessageRepository,
        conversations: ConversationRepository,
        contacts: ContactRepository,
        accounts: WhatsAppAccountRepository,
        whatsapp: WhatsAppService,
        notifications: NotificationService,
    ) -> None:
        self._session = session
        self._messages = messages
        self._conversations = conversations
        self._contacts = contacts
        self._accounts = accounts
        self._whatsapp = whatsapp
        self._notifications = notifications

    def list_for(
        self,
        workspace: Workspace,
        conversation_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 30,
    ) -> tuple[Sequence[Message], int]:
        workspace_id = workspace.id
        conversation = self._conversation(workspace_id, conversation_id)

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
        workspace: Workspace,
        conversation_id: uuid.UUID,
        payload: MessageCreate,
        *,
        sender_type: SenderType = SenderType.AGENT,
    ) -> Message:
        """Record a reply, then try to deliver it.

        `sender_type` is the one thing that differs between a person
        typing and the assistant answering: everything else -- written
        first, committed, delivered, marked -- has to be identical, or the
        two would be two delivery paths with two sets of bugs. It defaults
        to the agent, so the only caller that can produce an `ai` message
        is the one that means to.

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
        workspace_id = workspace.id
        conversation = self._conversation(workspace_id, conversation_id)

        if conversation.is_closed:
            raise ConversationClosedError(conversation.id)

        message = self._messages.create(
            workspace_id=workspace_id,
            conversation_id=conversation.id,
            sender_type=sender_type,
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
        except MessagingProviderError as exc:
            # Recorded on the message and then re-raised. The agent is
            # told it failed, and the thread shows why rather than showing
            # a reply that looks like it went.
            message.status = MessageStatus.FAILED
            # And the administrators are told, once. A provider outage
            # produces one failure per message, and one notification per
            # failure would bury the problem under itself -- so this kind
            # does not repeat while it is still unread. See
            # NotificationService.
            self._notifications.tell_everyone(
                workspace_id=workspace_id,
                roles=MAY_ADMINISTER,
                kind=NotificationKind.MESSAGE_DELIVERY_FAILED,
                title="A message could not be delivered",
                body=str(exc),
                meta={"conversation_id": str(conversation.id)},
            )
            self._session.commit()
            raise

        message.status = MessageStatus.SENT
        message.external_message_id = sent.external_message_id
        message.sent_at = datetime.now(UTC)
        self._session.commit()

        return message

    def _conversation(
        self,
        workspace_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> Conversation:
        """The thread, if it belongs to this workspace.

        Read through the repository rather than through ConversationService
        so that adding a message needs the conversation table and nothing
        else -- the two services were otherwise coupled by one lookup, and
        that coupling is what would drag a caller's membership into a
        background job that has none.
        """
        conversation = self._conversations.get(workspace_id, conversation_id)

        if conversation is None:
            raise ConversationNotFoundError(workspace_id, conversation_id)

        return conversation

    def _touch(self, conversation: Conversation, message: Message) -> None:
        """Keep the inbox ordering honest, and clear the unread badge.

        Written in the same transaction as the message, so a thread cannot
        exist with a reply in it and a last_message_at that predates it.

        Replying marks the thread read because it is the strongest
        statement there is that somebody has read it, and a shared inbox
        still showing a badge on a conversation a colleague has just
        answered is one that gets answered twice. A client that opens a
        thread without replying says so with the read endpoint.
        """
        at = message.created_at or datetime.now(UTC)

        self._conversations.record_activity(conversation, at)
        self._conversations.mark_read(conversation, at)


def get_message_repository(session: SessionDep) -> MessageRepository:
    return MessageRepository(session)


MessageRepositoryDep = Annotated[MessageRepository, Depends(get_message_repository)]


def get_message_service(
    session: SessionDep,
    messages: MessageRepositoryDep,
    conversations: ConversationRepositoryDep,
    contacts: ContactRepositoryDep,
    accounts: WhatsAppAccountRepositoryDep,
    whatsapp: WhatsAppServiceDep,
    notifications: NotificationServiceDep,
) -> MessageService:
    return MessageService(
        session=session,
        messages=messages,
        conversations=conversations,
        contacts=contacts,
        accounts=accounts,
        whatsapp=whatsapp,
        notifications=notifications,
    )


MessageServiceDep = Annotated[MessageService, Depends(get_message_service)]
