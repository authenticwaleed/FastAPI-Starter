"""Phase 6 acceptance: messages persisted, and in the order they were said."""

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConversationClosedError,
    ConversationNotFoundError,
)
from app.models.message import Direction, MessageStatus, SenderType
from app.models.user import User
from app.repositories.contact_repository import ContactRepository
from app.repositories.conversation_event_repository import (
    ConversationEventRepository,
)
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.whatsapp_account_repository import (
    WhatsAppAccountRepository,
)
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.contact import ContactCreate
from app.schemas.conversation import ConversationCreate
from app.schemas.message import MessageCreate
from app.schemas.workspace import WorkspaceCreate
from app.services.contact_service import ContactService
from app.services.conversation_service import ConversationService
from app.services.message_service import MessageService
from app.services.whatsapp_service import WhatsAppService
from app.services.workspace_service import WorkspaceService
from tests.support.messaging import FakeMessagingProvider
from tests.support.services import notification_service

NUMBER = "+923001234567"


@pytest.fixture
def workspaces(
    db_session: Session,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> WorkspaceService:
    return WorkspaceService(
        session=db_session,
        workspaces=workspace_repository,
        memberships=membership_repository,
    )


@pytest.fixture
def conversations(
    db_session: Session,
    conversation_repository: ConversationRepository,
    contact_repository: ContactRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> ConversationService:
    return ConversationService(
        session=db_session,
        conversations=conversation_repository,
        contacts=contact_repository,
        memberships=membership_repository,
        events=ConversationEventRepository(db_session),
        notifications=notification_service(db_session),
    )


@pytest.fixture
def provider() -> FakeMessagingProvider:
    return FakeMessagingProvider()


@pytest.fixture
def whatsapp_accounts(db_session: Session) -> WhatsAppAccountRepository:
    return WhatsAppAccountRepository(db_session)


@pytest.fixture
def service(
    db_session: Session,
    message_repository: MessageRepository,
    conversation_repository: ConversationRepository,
    contact_repository: ContactRepository,
    whatsapp_accounts: WhatsAppAccountRepository,
    conversations: ConversationService,
    provider: FakeMessagingProvider,
) -> MessageService:
    """A message service with no WhatsApp number connected.

    Which is the state these tests are about: what happens to a reply
    before there is anywhere for it to go. Delivery has its own file.
    """
    return MessageService(
        session=db_session,
        messages=message_repository,
        conversations=conversation_repository,
        contacts=contact_repository,
        accounts=whatsapp_accounts,
        whatsapp=WhatsAppService(
            session=db_session,
            accounts=whatsapp_accounts,
            provider=provider,
        ),
        notifications=notification_service(db_session),
    )


class Business:
    def __init__(
        self,
        session: Session,
        workspaces: WorkspaceService,
        contact_repository: ContactRepository,
        conversations: ConversationService,
        slug: str,
    ) -> None:
        user = User(
            name="Someone",
            email=f"owner-{slug}@example.com",
            hashed_password="not a real hash",
        )
        session.add(user)
        session.flush()

        self.workspace = workspaces.create(
            WorkspaceCreate(name=slug.title(), slug=slug),
            creator=user,
        )
        self.access = workspaces.access(self.workspace.id, user)

        contacts = ContactService(session=session, contacts=contact_repository)
        contact = contacts.create(self.access, ContactCreate(phone_number=NUMBER))
        self.conversation = conversations.create(
            self.access,
            ConversationCreate(contact_id=contact.id),
        ).conversation


@pytest.fixture
def acme(
    db_session: Session,
    workspaces: WorkspaceService,
    contact_repository: ContactRepository,
    conversations: ConversationService,
) -> Business:
    return Business(
        db_session, workspaces, contact_repository, conversations, "acme-fashion"
    )


@pytest.fixture
def rival(
    db_session: Session,
    workspaces: WorkspaceService,
    contact_repository: ContactRepository,
    conversations: ConversationService,
) -> Business:
    return Business(
        db_session, workspaces, contact_repository, conversations, "rival-store"
    )


def _send(service: MessageService, business: Business, text: str):
    return service.send(
        business.workspace,
        business.conversation.id,
        MessageCreate(text=text),
    )


def test_a_reply_is_persisted_as_an_outbound_agent_message(
    service: MessageService,
    acme: Business,
) -> None:
    message = _send(service, acme, "Hello, how can I help?")

    assert message.text_body == "Hello, how can I help?"
    assert message.sender_type == SenderType.AGENT
    assert message.direction == Direction.OUTBOUND
    assert message.conversation_id == acme.conversation.id
    assert message.workspace_id == acme.workspace.id


def test_a_reply_is_queued_when_there_is_nowhere_to_send_it(
    service: MessageService,
    acme: Business,
) -> None:
    # No number connected, so nothing delivers it. A message marked sent
    # that never left the building tells an agent their customer was
    # answered.
    assert _send(service, acme, "hello").status == MessageStatus.QUEUED


def test_sending_moves_the_conversation_up_the_inbox(
    service: MessageService,
    acme: Business,
) -> None:
    assert acme.conversation.last_message_at is None

    message = _send(service, acme, "hello")

    assert acme.conversation.last_message_at == message.created_at


def test_a_thread_reads_back_newest_first(
    service: MessageService,
    acme: Business,
) -> None:
    # All three share a created_at, because now() is fixed for the
    # transaction. The sequence is what keeps them in the order they were
    # said rather than a random one.
    for index in range(3):
        _send(service, acme, f"line {index}")

    messages, total = service.list_for(acme.workspace, acme.conversation.id)

    assert total == 3
    assert [message.text_body for message in messages] == ["line 2", "line 1", "line 0"]


def test_the_order_is_the_same_every_time_it_is_read(
    service: MessageService,
    acme: Business,
) -> None:
    for index in range(6):
        _send(service, acme, f"line {index}")

    first = [m.id for m in service.list_for(acme.workspace, acme.conversation.id)[0]]
    again = [m.id for m in service.list_for(acme.workspace, acme.conversation.id)[0]]

    assert first == again


def test_a_thread_is_paginated(service: MessageService, acme: Business) -> None:
    for index in range(5):
        _send(service, acme, f"line {index}")

    page_one, total = service.list_for(
        acme.workspace, acme.conversation.id, page=1, page_size=2
    )
    page_two, _ = service.list_for(
        acme.workspace, acme.conversation.id, page=2, page_size=2
    )

    assert total == 5
    assert [m.text_body for m in page_one] == ["line 4", "line 3"]
    assert [m.text_body for m in page_two] == ["line 2", "line 1"]


def test_a_closed_conversation_refuses_a_reply(
    service: MessageService,
    conversations: ConversationService,
    acme: Business,
) -> None:
    # Reopening is a decision somebody makes, not something a reply does
    # silently.
    conversations.close(acme.access, acme.conversation.id)

    with pytest.raises(ConversationClosedError):
        _send(service, acme, "are you still there?")


def test_a_reopened_conversation_accepts_replies_again(
    service: MessageService,
    conversations: ConversationService,
    acme: Business,
) -> None:
    conversations.close(acme.access, acme.conversation.id)
    conversations.reopen(acme.access, acme.conversation.id)

    assert _send(service, acme, "we are back").status == MessageStatus.QUEUED


def test_another_business_cannot_read_your_thread(
    service: MessageService,
    acme: Business,
    rival: Business,
) -> None:
    _send(service, acme, "private")

    with pytest.raises(ConversationNotFoundError):
        service.list_for(rival.workspace, acme.conversation.id)


def test_another_business_cannot_write_into_your_thread(
    service: MessageService,
    acme: Business,
    rival: Business,
) -> None:
    with pytest.raises(ConversationNotFoundError):
        service.send(
            rival.workspace,
            acme.conversation.id,
            MessageCreate(text="who are you"),
        )


def test_one_thread_does_not_show_another_ones_messages(
    service: MessageService,
    acme: Business,
    rival: Business,
) -> None:
    _send(service, acme, "mine")
    _send(service, rival, "theirs")

    messages, total = service.list_for(acme.workspace, acme.conversation.id)

    assert total == 1
    assert [m.text_body for m in messages] == ["mine"]
