"""Phase 7 acceptance: an agent's reply, actually leaving the building."""

import pytest
from sqlalchemy.orm import Session

from app.core.encryption import encrypt
from app.core.exceptions import MessagingProviderError
from app.models.message import MessageStatus
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
from tests.support.whatsapp import PHONE_NUMBER_ID

CUSTOMER = "+923001234567"
TOKEN = "a-provider-access-token"


@pytest.fixture
def provider() -> FakeMessagingProvider:
    return FakeMessagingProvider()


class Setup:
    """A workspace with a contact, a conversation, and a way to send."""

    def __init__(
        self,
        db_session: Session,
        workspace_repository: WorkspaceRepository,
        membership_repository: WorkspaceMembershipRepository,
        contact_repository: ContactRepository,
        conversation_repository: ConversationRepository,
        message_repository: MessageRepository,
        accounts: WhatsAppAccountRepository,
        provider: FakeMessagingProvider,
    ) -> None:
        user = User(
            name="Owner",
            email="owner@example.com",
            hashed_password="not a real hash",
        )
        db_session.add(user)
        db_session.flush()

        workspaces = WorkspaceService(
            session=db_session,
            workspaces=workspace_repository,
            memberships=membership_repository,
        )
        workspace = workspaces.create(
            WorkspaceCreate(name="Acme Fashion", slug="acme-fashion"),
            creator=user,
        )
        self.access = workspaces.access(workspace.id, user)
        self.accounts = accounts
        self.workspace = workspace
        self.workspace_id = workspace.id

        contacts = ContactService(session=db_session, contacts=contact_repository)
        contact = contacts.create(self.access, ContactCreate(phone_number=CUSTOMER))

        self.conversations = ConversationService(
            session=db_session,
            conversations=conversation_repository,
            contacts=contact_repository,
            memberships=membership_repository,
            events=ConversationEventRepository(db_session),
            notifications=notification_service(db_session),
        )
        self.conversation = self.conversations.create(
            self.access,
            ConversationCreate(contact_id=contact.id),
        ).conversation

        self.service = MessageService(
            session=db_session,
            messages=message_repository,
            conversations=conversation_repository,
            contacts=contact_repository,
            accounts=accounts,
            whatsapp=WhatsAppService(
                session=db_session,
                accounts=accounts,
                provider=provider,
            ),
            notifications=notification_service(db_session),
        )

    def connect(self) -> None:
        self.accounts.create(
            workspace_id=self.workspace_id,
            provider="meta_cloud",  # type: ignore[arg-type]
            phone_number="+15550001111",
            external_phone_number_id=PHONE_NUMBER_ID,
            external_business_account_id=None,
            access_token_encrypted=encrypt(TOKEN),
        )

    def send(self, text: str = "We do, in black."):
        return self.service.send(
            self.workspace,
            self.conversation.id,
            MessageCreate(text=text),
        )


@pytest.fixture
def setup(
    db_session: Session,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    contact_repository: ContactRepository,
    conversation_repository: ConversationRepository,
    message_repository: MessageRepository,
    whatsapp_account_repository: WhatsAppAccountRepository,
    provider: FakeMessagingProvider,
) -> Setup:
    return Setup(
        db_session,
        workspace_repository,
        membership_repository,
        contact_repository,
        conversation_repository,
        message_repository,
        whatsapp_account_repository,
        provider,
    )


def test_a_reply_goes_to_the_provider(
    setup: Setup,
    provider: FakeMessagingProvider,
) -> None:
    setup.connect()

    setup.send("We do, in black.")

    assert len(provider.sent) == 1
    attempt = provider.sent[0]
    assert attempt.to == CUSTOMER
    assert attempt.text == "We do, in black."
    assert attempt.phone_number_id == PHONE_NUMBER_ID
    # Decrypted for exactly the length of the call, and never before.
    assert attempt.access_token == TOKEN


def test_a_delivered_reply_records_the_providers_id(
    setup: Setup,
    provider: FakeMessagingProvider,
) -> None:
    # Without it a later status notification has nothing to attach to.
    setup.connect()
    provider.next_message_id = "wamid.OUT99"

    message = setup.send()

    assert message.status == MessageStatus.SENT
    assert message.external_message_id == "wamid.OUT99"
    assert message.sent_at is not None


def test_a_reply_with_no_number_connected_stays_queued(
    setup: Setup,
    provider: FakeMessagingProvider,
) -> None:
    message = setup.send()

    assert message.status == MessageStatus.QUEUED
    assert message.external_message_id is None
    assert provider.sent == []


def test_a_provider_failure_is_recorded_on_the_message(
    setup: Setup,
    provider: FakeMessagingProvider,
) -> None:
    setup.connect()
    provider.fail_with = "the provider rejected the message (400)"

    with pytest.raises(MessagingProviderError):
        setup.send()


def test_a_failed_reply_is_kept_and_marked_failed(
    setup: Setup,
    provider: FakeMessagingProvider,
    message_repository: MessageRepository,
) -> None:
    # The thread shows why, rather than showing a reply that looks like it
    # went, and rather than losing what the agent typed.
    setup.connect()
    provider.fail_with = "boom"

    with pytest.raises(MessagingProviderError):
        setup.send("this will not go")

    messages = message_repository.list_for_conversation(
        setup.workspace_id,
        setup.conversation.id,
        limit=10,
        offset=0,
    )

    assert [m.text_body for m in messages] == ["this will not go"]
    assert messages[0].status == MessageStatus.FAILED


def test_the_providers_own_words_do_not_reach_the_client(
    setup: Setup,
    provider: FakeMessagingProvider,
) -> None:
    # An error written for whoever built the integration is not written
    # for the agent who pressed send.
    setup.connect()
    provider.fail_with = "OAuthException: token for app 12345 is invalid"

    with pytest.raises(MessagingProviderError) as failure:
        setup.send()

    assert failure.value.detail == "The message could not be delivered right now"
    assert "12345" not in failure.value.detail


def test_a_reply_still_moves_the_conversation_up_the_inbox(
    setup: Setup,
) -> None:
    setup.connect()

    setup.send()

    assert setup.conversation.last_message_at is not None
