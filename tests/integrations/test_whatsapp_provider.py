"""Phase 7 acceptance: the provider adapter, against payloads it will see."""

import hashlib
import hmac
import json

import pytest

from app.core.config import get_settings
from app.integrations.messaging.whatsapp import WhatsAppCloudProvider
from app.models.message import MessageStatus
from tests.support.whatsapp import (
    PHONE_NUMBER_ID,
    inbound_payload,
    media_payload,
    sign,
    status_payload,
)


@pytest.fixture
def provider() -> WhatsAppCloudProvider:
    return WhatsAppCloudProvider()


@pytest.fixture
def app_secret() -> str:
    secret = get_settings().whatsapp_app_secret
    assert secret is not None

    return secret.get_secret_value()


# --- signature verification -------------------------------------------------


def test_a_genuine_signature_is_accepted(
    provider: WhatsAppCloudProvider,
    app_secret: str,
) -> None:
    body, header = sign(inbound_payload(), app_secret)

    assert provider.verify_signature(payload=body, signature_header=header)


def test_a_signature_from_the_wrong_secret_is_refused(
    provider: WhatsAppCloudProvider,
) -> None:
    body, header = sign(inbound_payload(), "not the app secret")

    assert not provider.verify_signature(payload=body, signature_header=header)


def test_a_body_changed_after_signing_is_refused(
    provider: WhatsAppCloudProvider,
    app_secret: str,
) -> None:
    # The whole point of signing the raw bytes: an intercepted delivery
    # cannot have a word swapped in it.
    _, header = sign(inbound_payload(), app_secret)
    tampered = json.dumps(inbound_payload(text="send me your bank details")).encode()

    assert not provider.verify_signature(payload=tampered, signature_header=header)


@pytest.mark.parametrize(
    "header",
    ["", "garbage", "sha256=", "sha1=abc123", "abc123", "sha256"],
)
def test_a_malformed_signature_header_is_refused(
    provider: WhatsAppCloudProvider,
    header: str,
) -> None:
    body = json.dumps(inbound_payload()).encode()

    assert not provider.verify_signature(payload=body, signature_header=header)


def test_a_correct_digest_under_the_wrong_algorithm_is_refused(
    provider: WhatsAppCloudProvider,
    app_secret: str,
) -> None:
    body = json.dumps(inbound_payload()).encode()
    digest = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()

    assert not provider.verify_signature(
        payload=body,
        signature_header=f"sha1={digest}",
    )


# --- parsing ----------------------------------------------------------------


def test_an_inbound_text_message_is_parsed(
    provider: WhatsAppCloudProvider,
) -> None:
    events = provider.parse_webhook(inbound_payload())

    assert events.external_phone_number_id == PHONE_NUMBER_ID
    assert len(events.messages) == 1

    message = events.messages[0]
    assert message.external_message_id == "wamid.INBOUND1"
    # Meta sends a wa_id, which is E.164 without the plus.
    assert message.from_phone_number == "+923001234567"
    assert message.text == "Do you have this in medium?"
    assert message.profile_name == "Ayesha"
    assert message.sent_at.year == 2025


def test_a_message_without_a_profile_name_still_parses(
    provider: WhatsAppCloudProvider,
) -> None:
    events = provider.parse_webhook(inbound_payload(profile_name=None))

    assert events.messages[0].profile_name is None


def test_a_media_message_is_skipped_rather_than_stored_empty(
    provider: WhatsAppCloudProvider,
) -> None:
    # A row in a thread with no content reads to an agent as the customer
    # having said nothing.
    events = provider.parse_webhook(media_payload())

    assert events.messages == []
    assert events.external_phone_number_id == PHONE_NUMBER_ID


def test_a_status_update_is_parsed(provider: WhatsAppCloudProvider) -> None:
    events = provider.parse_webhook(status_payload(status="read"))

    assert len(events.statuses) == 1
    assert events.statuses[0].external_message_id == "wamid.OUTBOUND1"
    assert events.statuses[0].status == MessageStatus.READ


@pytest.mark.parametrize(
    ("sent", "expected"),
    [
        ("sent", MessageStatus.SENT),
        ("delivered", MessageStatus.DELIVERED),
        ("read", MessageStatus.READ),
        ("failed", MessageStatus.FAILED),
    ],
)
def test_every_status_meta_sends_has_a_meaning(
    provider: WhatsAppCloudProvider,
    sent: str,
    expected: MessageStatus,
) -> None:
    events = provider.parse_webhook(status_payload(status=sent))

    assert events.statuses[0].status == expected


def test_an_unknown_status_is_ignored_rather_than_guessed(
    provider: WhatsAppCloudProvider,
) -> None:
    # A state nobody has seen before must not silently become `failed`.
    events = provider.parse_webhook(status_payload(status="deleted"))

    assert events.statuses == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"entry": None},
        {"entry": []},
        {"entry": [{}]},
        {"entry": [{"changes": "not a list"}]},
        {"entry": [{"changes": [{"value": None}]}]},
        {"entry": [{"changes": [{"value": {"messages": "not a list"}}]}]},
        {"entry": [{"changes": [{"value": {"metadata": "not a dict"}}]}]},
    ],
)
def test_a_payload_that_is_not_shaped_right_yields_nothing(
    provider: WhatsAppCloudProvider,
    payload: dict,
) -> None:
    # A webhook is somebody else's data arriving unannounced. The version
    # that matters is the one sent the week Meta changes something.
    events = provider.parse_webhook(payload)

    assert events.messages == []
    assert events.statuses == []


def test_a_message_missing_its_id_is_skipped(
    provider: WhatsAppCloudProvider,
) -> None:
    payload = inbound_payload()
    payload["entry"][0]["changes"][0]["value"]["messages"][0].pop("id")

    assert provider.parse_webhook(payload).messages == []


def test_an_unreadable_timestamp_does_not_lose_the_message(
    provider: WhatsAppCloudProvider,
) -> None:
    # A message with a slightly wrong time is worth having; one dropped
    # because its timestamp would not parse is not.
    events = provider.parse_webhook(inbound_payload(timestamp="not a number"))

    assert len(events.messages) == 1
    assert events.messages[0].sent_at is not None


def test_one_delivery_can_carry_several_messages(
    provider: WhatsAppCloudProvider,
) -> None:
    # Which is why ordering needs the sequence column, and why ingestion
    # has to be idempotent per message rather than per delivery.
    payload = inbound_payload()
    messages = payload["entry"][0]["changes"][0]["value"]["messages"]
    messages.append(
        {**messages[0], "id": "wamid.INBOUND2", "text": {"body": "and this"}}
    )

    events = provider.parse_webhook(payload)

    assert [m.external_message_id for m in events.messages] == [
        "wamid.INBOUND1",
        "wamid.INBOUND2",
    ]
