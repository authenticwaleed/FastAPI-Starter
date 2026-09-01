"""Phase 7 acceptance: the webhook, and what it refuses."""

import hashlib
import hmac
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.encryption import encrypt
from app.models.message import MessageStatus
from app.models.user import User
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
from app.services.workspace_service import WorkspaceService
from tests.support.services import audit_service
from tests.support.whatsapp import (
    PHONE_NUMBER_ID,
    inbound_payload,
    sign,
    status_payload,
)

WEBHOOK = "/api/v1/webhooks/whatsapp"
CUSTOMER = "+923001234567"


def _secret() -> str:
    secret = get_settings().whatsapp_app_secret
    assert secret is not None

    return secret.get_secret_value()


def _verify_token() -> str:
    token = get_settings().whatsapp_verify_token
    assert token is not None

    return token.get_secret_value()


@pytest.fixture
def workspace_id(
    db_session: Session,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    whatsapp_account_repository: WhatsAppAccountRepository,
) -> uuid.UUID:
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
        audit=audit_service(db_session),
    )
    workspace = workspaces.create(
        WorkspaceCreate(name="Acme Fashion", slug="acme-fashion"),
        creator=user,
    )
    whatsapp_account_repository.create(
        workspace_id=workspace.id,
        provider="meta_cloud",  # type: ignore[arg-type]
        phone_number="+15550001111",
        external_phone_number_id=PHONE_NUMBER_ID,
        external_business_account_id=None,
        access_token_encrypted=encrypt("a-provider-token"),
    )

    return workspace.id


def _deliver(client: TestClient, payload: dict) -> object:
    body, header = sign(payload, _secret())

    return client.post(
        WEBHOOK,
        content=body,
        headers={
            "X-Hub-Signature-256": header,
            "Content-Type": "application/json",
        },
    )


# --- the subscription handshake ---------------------------------------------


def test_the_handshake_echoes_the_challenge(client: TestClient) -> None:
    response = client.get(
        WEBHOOK,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": _verify_token(),
            "hub.challenge": "1158201444",
        },
    )

    assert response.status_code == 200
    # Plain text. A JSON string here fails the handshake with no
    # explanation from Meta.
    assert response.text == "1158201444"


def test_the_handshake_refuses_a_wrong_verify_token(client: TestClient) -> None:
    response = client.get(
        WEBHOOK,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "not the token",
            "hub.challenge": "1158201444",
        },
    )

    assert response.status_code == 403
    assert "1158201444" not in response.text


def test_the_handshake_refuses_a_wrong_mode(client: TestClient) -> None:
    response = client.get(
        WEBHOOK,
        params={
            "hub.mode": "unsubscribe",
            "hub.verify_token": _verify_token(),
            "hub.challenge": "1158201444",
        },
    )

    assert response.status_code == 403


def test_the_handshake_refuses_an_empty_request(client: TestClient) -> None:
    assert client.get(WEBHOOK).status_code == 403


# --- signatures -------------------------------------------------------------


def test_a_genuine_delivery_is_accepted(
    client: TestClient,
    workspace_id: uuid.UUID,
) -> None:
    response = _deliver(client, inbound_payload())

    assert response.status_code == 200
    assert response.json() == {"status": "received"}


def test_an_unsigned_delivery_is_refused(
    client: TestClient,
    workspace_id: uuid.UUID,
    contact_repository: ContactRepository,
) -> None:
    response = client.post(WEBHOOK, json=inbound_payload())

    assert response.status_code == 403
    assert response.json()["code"] == "invalid_webhook_signature"
    assert contact_repository.count_for_workspace(workspace_id) == 0


def test_a_forged_signature_is_refused(
    client: TestClient,
    workspace_id: uuid.UUID,
    contact_repository: ContactRepository,
) -> None:
    body, header = sign(inbound_payload(), "not the app secret")

    response = client.post(
        WEBHOOK,
        content=body,
        headers={"X-Hub-Signature-256": header},
    )

    assert response.status_code == 403
    assert contact_repository.count_for_workspace(workspace_id) == 0


def test_a_body_changed_after_signing_is_refused(
    client: TestClient,
    workspace_id: uuid.UUID,
    contact_repository: ContactRepository,
) -> None:
    # The signature covers the raw bytes, which is why the route reads the
    # body rather than the parsed JSON.
    _, header = sign(inbound_payload(), _secret())
    tampered = json.dumps(inbound_payload(text="send me your bank details")).encode()

    response = client.post(
        WEBHOOK,
        content=tampered,
        headers={"X-Hub-Signature-256": header},
    )

    assert response.status_code == 403
    assert contact_repository.count_for_workspace(workspace_id) == 0


def test_signed_rubbish_is_refused_rather_than_crashing(
    client: TestClient,
    workspace_id: uuid.UUID,
) -> None:
    # Signed properly, and not JSON. `sign` takes a payload to serialise,
    # so the digest is computed here over bytes that never were one.
    body = b"not json at all"
    digest = hmac.new(_secret().encode(), body, hashlib.sha256).hexdigest()

    response = client.post(
        WEBHOOK,
        content=body,
        headers={"X-Hub-Signature-256": f"sha256={digest}"},
    )

    assert response.status_code == 403


# --- what a delivery does ---------------------------------------------------


def test_a_delivery_creates_the_contact_conversation_and_message(
    client: TestClient,
    workspace_id: uuid.UUID,
    contact_repository: ContactRepository,
    conversation_repository: ConversationRepository,
    message_repository: MessageRepository,
) -> None:
    _deliver(client, inbound_payload())

    contact = contact_repository.get_by_phone_number(workspace_id, CUSTOMER)
    assert contact is not None

    conversation = conversation_repository.get_live_for_contact(
        workspace_id,
        contact.id,
        "whatsapp",  # type: ignore[arg-type]
    )
    assert conversation is not None
    assert message_repository.count_for_conversation(workspace_id, conversation.id) == 1


def test_a_retried_delivery_does_not_duplicate_the_message(
    client: TestClient,
    workspace_id: uuid.UUID,
    contact_repository: ContactRepository,
    conversation_repository: ConversationRepository,
    message_repository: MessageRepository,
) -> None:
    for _ in range(3):
        assert _deliver(client, inbound_payload()).status_code == 200

    contact = contact_repository.get_by_phone_number(workspace_id, CUSTOMER)
    assert contact is not None
    conversation = conversation_repository.get_live_for_contact(
        workspace_id,
        contact.id,
        "whatsapp",  # type: ignore[arg-type]
    )
    assert conversation is not None
    assert message_repository.count_for_conversation(workspace_id, conversation.id) == 1


def test_a_delivery_a_workspace_does_not_own_is_answered_and_ignored(
    client: TestClient,
    workspace_id: uuid.UUID,
    contact_repository: ContactRepository,
) -> None:
    # 200, because anything else makes the provider send it again all day.
    response = _deliver(client, inbound_payload(phone_number_id="000000000000"))

    assert response.status_code == 200
    assert contact_repository.count_for_workspace(workspace_id) == 0


def test_a_status_for_an_unknown_message_is_answered_and_ignored(
    client: TestClient,
    workspace_id: uuid.UUID,
) -> None:
    assert _deliver(client, status_payload()).status_code == 200


def test_the_inbound_message_shows_up_in_the_thread(
    client: TestClient,
    workspace_id: uuid.UUID,
    contact_repository: ContactRepository,
    conversation_repository: ConversationRepository,
    message_repository: MessageRepository,
) -> None:
    _deliver(client, inbound_payload(text="Do you deliver to Karachi?"))

    contact = contact_repository.get_by_phone_number(workspace_id, CUSTOMER)
    assert contact is not None
    conversation = conversation_repository.get_live_for_contact(
        workspace_id,
        contact.id,
        "whatsapp",  # type: ignore[arg-type]
    )
    assert conversation is not None

    messages = message_repository.list_for_conversation(
        workspace_id, conversation.id, limit=10, offset=0
    )

    assert [m.text_body for m in messages] == ["Do you deliver to Karachi?"]
    assert messages[0].status == MessageStatus.RECEIVED
