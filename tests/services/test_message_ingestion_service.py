"""Phase 7 acceptance: an inbound message, handled once however often it
arrives."""

import pytest
from sqlalchemy.orm import Session

from app.core.encryption import encrypt
from app.core.exceptions import InvalidWebhookError
from app.models.contact import ContactStatus
from app.models.conversation import ConversationStatus
from app.models.message import Direction, MessageStatus, SenderType
from app.models.user import User
from app.models.whatsapp_account import WhatsAppAccount
from app.repositories.contact_repository import ContactRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.whatsapp_account_repository import (
    WhatsAppAccountRepository,
)
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.workspace import WorkspaceCreate
from app.services.message_ingestion_service import MessageIngestionService
from app.services.workspace_service import WorkspaceService
from tests.support.messaging import FakeMessagingProvider
from tests.support.whatsapp import (
    PHONE_NUMBER_ID,
    inbound_payload,
    media_payload,
    status_payload,
)

CUSTOMER = "+923001234567"


@pytest.fixture
def provider() -> FakeMessagingProvider:
    return FakeMessagingProvider()


@pytest.fixture
def service(
    db_session: Session,
    whatsapp_account_repository: WhatsAppAccountRepository,
    contact_repository: ContactRepository,
    conversation_repository: ConversationRepository,
    message_repository: MessageRepository,
    provider: FakeMessagingProvider,
) -> MessageIngestionService:
    return MessageIngestionService(
        session=db_session,
        accounts=whatsapp_account_repository,
        contacts=contact_repository,
        conversations=conversation_repository,
        messages=message_repository,
        provider=provider,
    )


@pytest.fixture
def account(
    db_session: Session,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    whatsapp_account_repository: WhatsAppAccountRepository,
) -> WhatsAppAccount:
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

    return whatsapp_account_repository.create(
        workspace_id=workspace.id,
        provider="meta_cloud",  # type: ignore[arg-type]
        phone_number="+15550001111",
        external_phone_number_id=PHONE_NUMBER_ID,
        external_business_account_id=None,
        access_token_encrypted=encrypt("a-provider-token"),
    )


# --- verification -----------------------------------------------------------


def test_a_delivery_with_no_signature_is_refused(
    service: MessageIngestionService,
) -> None:
    with pytest.raises(InvalidWebhookError):
        service.verify(payload=b"{}", signature_header=None)


def test_a_delivery_the_provider_rejects_is_refused(
    service: MessageIngestionService,
    provider: FakeMessagingProvider,
) -> None:
    provider.signature_is_valid = False

    with pytest.raises(InvalidWebhookError):
        service.verify(payload=b"{}", signature_header="sha256=whatever")


# --- the incoming flow ------------------------------------------------------


def test_an_inbound_message_creates_the_contact(
    service: MessageIngestionService,
    account: WhatsAppAccount,
    contact_repository: ContactRepository,
) -> None:
    service.ingest(inbound_payload())

    contact = contact_repository.get_by_phone_number(account.workspace_id, CUSTOMER)

    assert contact is not None
    assert contact.name == "Ayesha"
    assert contact.source == "whatsapp"
    assert contact.status == ContactStatus.LEAD


def test_an_inbound_message_opens_a_conversation(
    service: MessageIngestionService,
    account: WhatsAppAccount,
    contact_repository: ContactRepository,
    conversation_repository: ConversationRepository,
) -> None:
    service.ingest(inbound_payload())

    contact = contact_repository.get_by_phone_number(account.workspace_id, CUSTOMER)
    assert contact is not None

    conversation = conversation_repository.get_live_for_contact(
        account.workspace_id,
        contact.id,
        "whatsapp",  # type: ignore[arg-type]
    )
    assert conversation is not None
    assert conversation.last_message_at is not None


def test_the_message_is_recorded_as_an_inbound_customer_message(
    service: MessageIngestionService,
    account: WhatsAppAccount,
    message_repository: MessageRepository,
) -> None:
    service.ingest(inbound_payload())

    message = message_repository.get_by_external_id(
        account.workspace_id,
        "wamid.INBOUND1",
    )

    assert message is not None
    assert message.sender_type == SenderType.CUSTOMER
    assert message.direction == Direction.INBOUND
    assert message.status == MessageStatus.RECEIVED
    assert message.text_body == "Do you have this in medium?"
    assert message.received_at is not None


def test_the_same_delivery_twice_writes_one_message(
    service: MessageIngestionService,
    account: WhatsAppAccount,
    message_repository: MessageRepository,
    contact_repository: ContactRepository,
    conversation_repository: ConversationRepository,
) -> None:
    # The rule the plan states outright. A provider retries whenever it
    # does not get a prompt 200 -- including when it did and the response
    # was lost.
    service.ingest(inbound_payload())
    service.ingest(inbound_payload())
    service.ingest(inbound_payload())

    contact = contact_repository.get_by_phone_number(account.workspace_id, CUSTOMER)
    assert contact is not None
    conversation = conversation_repository.get_live_for_contact(
        account.workspace_id,
        contact.id,
        "whatsapp",  # type: ignore[arg-type]
    )
    assert conversation is not None

    assert (
        message_repository.count_for_conversation(account.workspace_id, conversation.id)
        == 1
    )


def test_a_second_message_joins_the_same_conversation(
    service: MessageIngestionService,
    account: WhatsAppAccount,
    contact_repository: ContactRepository,
    conversation_repository: ConversationRepository,
    message_repository: MessageRepository,
) -> None:
    service.ingest(inbound_payload(message_id="wamid.A", text="first"))
    service.ingest(inbound_payload(message_id="wamid.B", text="second"))

    contact = contact_repository.get_by_phone_number(account.workspace_id, CUSTOMER)
    assert contact is not None
    conversation = conversation_repository.get_live_for_contact(
        account.workspace_id,
        contact.id,
        "whatsapp",  # type: ignore[arg-type]
    )
    assert conversation is not None

    assert (
        message_repository.count_for_conversation(account.workspace_id, conversation.id)
        == 2
    )


def test_a_known_contact_is_not_duplicated(
    service: MessageIngestionService,
    account: WhatsAppAccount,
    contact_repository: ContactRepository,
) -> None:
    contact_repository.create(
        workspace_id=account.workspace_id,
        phone_number=CUSTOMER,
        name="Ayesha Khan",
        email=None,
        status=ContactStatus.CUSTOMER,
        source="manual",
        external_id=None,
        meta={},
    )

    service.ingest(inbound_payload())

    assert contact_repository.count_for_workspace(account.workspace_id) == 1


def test_a_name_the_business_typed_is_not_overwritten(
    service: MessageIngestionService,
    account: WhatsAppAccount,
    contact_repository: ContactRepository,
) -> None:
    # The profile name is whatever the customer set on their own device.
    contact_repository.create(
        workspace_id=account.workspace_id,
        phone_number=CUSTOMER,
        name="Ayesha Khan",
        email=None,
        status=ContactStatus.CUSTOMER,
        source="manual",
        external_id=None,
        meta={},
    )

    service.ingest(inbound_payload(profile_name="xX_ayesha_Xx"))

    contact = contact_repository.get_by_phone_number(account.workspace_id, CUSTOMER)
    assert contact is not None
    assert contact.name == "Ayesha Khan"


def test_a_nameless_contact_gains_the_profile_name(
    service: MessageIngestionService,
    account: WhatsAppAccount,
    contact_repository: ContactRepository,
) -> None:
    contact_repository.create(
        workspace_id=account.workspace_id,
        phone_number=CUSTOMER,
        name=None,
        email=None,
        status=ContactStatus.LEAD,
        source="manual",
        external_id=None,
        meta={},
    )

    service.ingest(inbound_payload(profile_name="Ayesha"))

    contact = contact_repository.get_by_phone_number(account.workspace_id, CUSTOMER)
    assert contact is not None
    assert contact.name == "Ayesha"


def test_a_closed_conversation_reopens_when_the_customer_writes_again(
    service: MessageIngestionService,
    account: WhatsAppAccount,
    contact_repository: ContactRepository,
    conversation_repository: ConversationRepository,
    message_repository: MessageRepository,
) -> None:
    # The plan's rule, and the reading an agent expects: a customer
    # replying to a thread they thought was finished gets that thread
    # back, not a second one beside it.
    service.ingest(inbound_payload(message_id="wamid.A"))

    contact = contact_repository.get_by_phone_number(account.workspace_id, CUSTOMER)
    assert contact is not None
    first = conversation_repository.get_live_for_contact(
        account.workspace_id,
        contact.id,
        "whatsapp",  # type: ignore[arg-type]
    )
    assert first is not None
    conversation_repository.set_status(
        first,
        ConversationStatus.CLOSED,
        closed_at=first.created_at,
    )

    service.ingest(inbound_payload(message_id="wamid.B"))

    reopened = conversation_repository.get_live_for_contact(
        account.workspace_id,
        contact.id,
        "whatsapp",  # type: ignore[arg-type]
    )
    assert reopened is not None
    assert reopened.id == first.id
    assert reopened.status == ConversationStatus.OPEN
    assert (
        message_repository.count_for_conversation(account.workspace_id, reopened.id)
        == 2
    )


def test_a_media_message_is_skipped_without_touching_anything(
    service: MessageIngestionService,
    account: WhatsAppAccount,
    contact_repository: ContactRepository,
) -> None:
    service.ingest(media_payload())

    assert contact_repository.count_for_workspace(account.workspace_id) == 0


def test_a_delivery_for_an_unconnected_number_is_ignored(
    service: MessageIngestionService,
    account: WhatsAppAccount,
    contact_repository: ContactRepository,
) -> None:
    # Ordinary during setup and after a disconnect.
    service.ingest(inbound_payload(phone_number_id="000000000000000"))

    assert contact_repository.count_for_workspace(account.workspace_id) == 0


def test_a_delivery_naming_no_number_is_ignored(
    service: MessageIngestionService,
    account: WhatsAppAccount,
) -> None:
    service.ingest({"entry": [{"changes": [{"value": {}}]}]})


# --- status updates ---------------------------------------------------------


@pytest.fixture
def outbound(
    account: WhatsAppAccount,
    contact_repository: ContactRepository,
    conversation_repository: ConversationRepository,
    message_repository: MessageRepository,
):
    contact = contact_repository.create(
        workspace_id=account.workspace_id,
        phone_number=CUSTOMER,
        name=None,
        email=None,
        status=ContactStatus.LEAD,
        source="whatsapp",
        external_id=None,
        meta={},
    )
    conversation = conversation_repository.create(
        workspace_id=account.workspace_id,
        contact_id=contact.id,
        channel="whatsapp",  # type: ignore[arg-type]
    )

    return message_repository.create(
        workspace_id=account.workspace_id,
        conversation_id=conversation.id,
        sender_type=SenderType.AGENT,
        direction=Direction.OUTBOUND,
        channel="whatsapp",  # type: ignore[arg-type]
        status=MessageStatus.SENT,
        text="We do, in black.",
        external_message_id="wamid.OUTBOUND1",
    )


def test_a_status_update_moves_the_message_on(
    service: MessageIngestionService,
    outbound,
) -> None:
    service.ingest(status_payload(status="delivered"))

    assert outbound.status == MessageStatus.DELIVERED


def test_statuses_advance_through_their_order(
    service: MessageIngestionService,
    outbound,
) -> None:
    service.ingest(status_payload(status="delivered"))
    service.ingest(status_payload(status="read"))

    assert outbound.status == MessageStatus.READ


def test_a_late_notification_cannot_walk_a_message_backwards(
    service: MessageIngestionService,
    outbound,
) -> None:
    # A provider's notifications are not ordered: `sent` can arrive after
    # `read` when a delivery was retried.
    service.ingest(status_payload(status="read"))
    service.ingest(status_payload(status="sent"))

    assert outbound.status == MessageStatus.READ


def test_a_failure_always_applies(
    service: MessageIngestionService,
    outbound,
) -> None:
    # Terminal information, and exactly the case an agent needs to see.
    service.ingest(status_payload(status="delivered"))
    service.ingest(status_payload(status="failed"))

    assert outbound.status == MessageStatus.FAILED


def test_a_status_for_a_message_nobody_has_is_ignored(
    service: MessageIngestionService,
    account: WhatsAppAccount,
) -> None:
    service.ingest(status_payload(message_id="wamid.NEVER_SENT"))
