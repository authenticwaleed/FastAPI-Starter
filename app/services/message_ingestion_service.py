import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidWebhookError
from app.db.session import SessionDep
from app.integrations.messaging.base import (
    InboundMessage,
    MessagingProvider,
    StatusUpdate,
)
from app.models.contact import Contact, ContactStatus
from app.models.conversation import Channel, Conversation, ConversationStatus
from app.models.message import Direction, MessageStatus, SenderType
from app.models.whatsapp_account import WhatsAppAccount
from app.repositories.contact_repository import ContactRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.whatsapp_account_repository import (
    WhatsAppAccountRepository,
)
from app.services.contact_service import ContactRepositoryDep
from app.services.conversation_service import ConversationRepositoryDep
from app.services.message_service import MessageRepositoryDep
from app.services.whatsapp_service import (
    MessagingProviderDep,
    WhatsAppAccountRepositoryDep,
)

logger = logging.getLogger(__name__)

# How far along a message is. A provider's notifications are not ordered:
# `sent` can arrive after `read` if one delivery was retried. Statuses only
# move forward, so a late one cannot walk a message backwards in an inbox
# somebody is reading.
_PROGRESS = {
    MessageStatus.QUEUED: 0,
    MessageStatus.SENT: 1,
    MessageStatus.DELIVERED: 2,
    MessageStatus.READ: 3,
}


class MessageIngestionService:
    """Everything that happens when a customer's message arrives.

    Every step is written to survive being run twice on the same delivery.
    A provider retries whenever it does not get a prompt 200 -- including
    when it did, and the response was lost -- so "handled once" cannot
    mean "delivered once". It has to mean that handling the same delivery
    again changes nothing.
    """

    def __init__(
        self,
        session: Session,
        accounts: WhatsAppAccountRepository,
        contacts: ContactRepository,
        conversations: ConversationRepository,
        messages: MessageRepository,
        provider: MessagingProvider,
    ) -> None:
        self._session = session
        self._accounts = accounts
        self._contacts = contacts
        self._conversations = conversations
        self._messages = messages
        self._provider = provider

    def verify(self, *, payload: bytes, signature_header: str | None) -> None:
        if not signature_header or not self._provider.verify_signature(
            payload=payload,
            signature_header=signature_header,
        ):
            raise InvalidWebhookError

    def ingest(self, payload: dict[str, Any]) -> None:
        """Handle one delivery, whatever it turns out to contain.

        Nothing here raises for a delivery that cannot be used. A webhook
        answering anything but 200 is a webhook the provider sends again,
        and the same unreadable payload retried for a day is worse than a
        line in the log saying it was skipped.
        """
        events = self._provider.parse_webhook(payload)

        if events.external_phone_number_id is None:
            logger.info("A webhook delivery named no phone number id; skipping")
            return

        account = self._accounts.get_by_phone_number_id(events.external_phone_number_id)

        if account is None:
            # A delivery for a number this installation does not have
            # connected. Ordinary during setup and after a disconnect.
            logger.info("A webhook arrived for a phone number id nobody has connected")
            return

        for message in events.messages:
            self._record_inbound(account, message)

        for update in events.statuses:
            self._record_status(account, update)

    def _record_inbound(
        self,
        account: WhatsAppAccount,
        inbound: InboundMessage,
    ) -> None:
        workspace_id = account.workspace_id

        if (
            self._messages.get_by_external_id(
                workspace_id,
                inbound.external_message_id,
            )
            is not None
        ):
            # The retry case, and the reason the unique index exists.
            logger.info("A webhook message was already recorded; skipping")
            return

        contact = self._contact_for(account, inbound)
        conversation = self._conversation_for(account, contact)

        try:
            message = self._messages.create(
                workspace_id=workspace_id,
                conversation_id=conversation.id,
                sender_type=SenderType.CUSTOMER,
                direction=Direction.INBOUND,
                channel=conversation.channel,
                status=MessageStatus.RECEIVED,
                text=inbound.text,
                external_message_id=inbound.external_message_id,
                received_at=inbound.sent_at,
            )
            self._conversations.record_activity(conversation, inbound.sent_at)
            self._session.commit()
        except IntegrityError:
            # Two deliveries of the same message can arrive at once, and
            # the check above is not a lock. The unique index on the
            # provider's id is what actually settles it.
            self._session.rollback()
            logger.info("A webhook message was recorded concurrently; skipping")
            return

        logger.info(
            "Recorded an inbound message on conversation %s",
            message.conversation_id,
        )

    def _contact_for(
        self,
        account: WhatsAppAccount,
        inbound: InboundMessage,
    ) -> Contact:
        """Find whoever sent this, or start knowing them.

        The number is the identity. The profile name is filled in only
        when nothing better is known -- it is whatever the customer set on
        their own device, so it is worth showing and should never
        overwrite a name the business typed itself.
        """
        workspace_id = account.workspace_id
        contact = self._contacts.get_by_phone_number(
            workspace_id,
            inbound.from_phone_number,
        )

        if contact is not None:
            if contact.name is None and inbound.profile_name:
                self._contacts.update(contact, name=inbound.profile_name)
                self._session.commit()

            return contact

        try:
            contact = self._contacts.create(
                workspace_id=workspace_id,
                phone_number=inbound.from_phone_number,
                name=inbound.profile_name,
                email=None,
                status=ContactStatus.LEAD,
                source="whatsapp",
                external_id=None,
                meta={},
            )
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            existing = self._contacts.get_by_phone_number(
                workspace_id,
                inbound.from_phone_number,
            )

            if existing is None:
                raise

            return existing

        return contact

    def _conversation_for(
        self,
        account: WhatsAppAccount,
        contact: Contact,
    ) -> Conversation:
        """The thread this belongs in, reopening or opening one as needed.

        A customer writing again after their conversation was resolved
        gets that conversation back rather than a second one beside it:
        the plan's rule, and the reading an agent expects when somebody
        replies to a thread they thought was finished.
        """
        workspace_id = account.workspace_id

        live = self._conversations.get_live_for_contact(
            workspace_id,
            contact.id,
            Channel.WHATSAPP,
        )

        if live is not None:
            return live

        closed = self._conversations.get_latest_closed_for_contact(
            workspace_id,
            contact.id,
            Channel.WHATSAPP,
        )

        if closed is not None:
            self._conversations.set_status(
                closed,
                ConversationStatus.OPEN,
                opened_at=datetime.now(UTC),
            )
            self._session.commit()

            return closed

        try:
            conversation = self._conversations.create(
                workspace_id=workspace_id,
                contact_id=contact.id,
                channel=Channel.WHATSAPP,
            )
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            live = self._conversations.get_live_for_contact(
                workspace_id,
                contact.id,
                Channel.WHATSAPP,
            )

            if live is None:
                raise

            return live

        return conversation

    def _record_status(
        self,
        account: WhatsAppAccount,
        update: StatusUpdate,
    ) -> None:
        message = self._messages.get_by_external_id(
            account.workspace_id,
            update.external_message_id,
        )

        if message is None:
            logger.info("A status arrived for a message this workspace does not have")
            return

        if not _advances(message.status, update.status):
            return

        message.status = update.status

        if update.status == MessageStatus.SENT and message.sent_at is None:
            message.sent_at = update.occurred_at

        self._session.commit()


def _advances(current: MessageStatus, incoming: MessageStatus) -> bool:
    """Whether a notification moves a message forward.

    `failed` always applies: it is terminal information, and a message
    that failed after appearing to be delivered is exactly the case an
    agent needs to see. Everything else only moves up.
    """
    if incoming == MessageStatus.FAILED:
        return current != MessageStatus.FAILED

    return _PROGRESS.get(incoming, -1) > _PROGRESS.get(current, -1)


def get_message_ingestion_service(
    session: SessionDep,
    accounts: WhatsAppAccountRepositoryDep,
    contacts: ContactRepositoryDep,
    conversations: ConversationRepositoryDep,
    messages: MessageRepositoryDep,
    provider: MessagingProviderDep,
) -> MessageIngestionService:
    return MessageIngestionService(
        session=session,
        accounts=accounts,
        contacts=contacts,
        conversations=conversations,
        messages=messages,
        provider=provider,
    )


MessageIngestionServiceDep = Annotated[
    MessageIngestionService,
    Depends(get_message_ingestion_service),
]
