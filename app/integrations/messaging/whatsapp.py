import hashlib
import hmac
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.exceptions import MessagingProviderError
from app.core.observability import observed
from app.integrations.messaging.base import (
    InboundMessage,
    SentMessage,
    StatusUpdate,
    WebhookEvents,
)
from app.models.message import MessageStatus

logger = logging.getLogger(__name__)

_GRAPH_URL = "https://graph.facebook.com/v21.0"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# What Meta calls a delivery state, in this application's vocabulary.
# Anything not listed is ignored rather than guessed at: a status nobody
# has seen before should not silently become `failed`.
_STATUSES = {
    "sent": MessageStatus.SENT,
    "delivered": MessageStatus.DELIVERED,
    "read": MessageStatus.READ,
    "failed": MessageStatus.FAILED,
}


class WhatsAppCloudProvider:
    """Meta's WhatsApp Cloud API.

    Everything Meta-shaped lives in this file: the URL, the envelope its
    webhooks arrive in, the header its signatures come under. Nothing
    above this layer knows any of it, which is what would let a second
    provider be added by writing a second one of these.
    """

    def send_text(
        self,
        *,
        phone_number_id: str,
        access_token: str,
        to: str,
        text: str,
    ) -> SentMessage:
        with observed("whatsapp", "send_text"):
            return self._post(
                phone_number_id=phone_number_id,
                access_token=access_token,
                to=to,
                text=text,
            )

    def _post(
        self,
        *,
        phone_number_id: str,
        access_token: str,
        to: str,
        text: str,
    ) -> SentMessage:
        """The call itself, so that what `observed` wraps is only the call.

        Split out rather than wrapped in place: the timing should cover the
        request and the reading of its answer, and nothing else.
        """
        try:
            response = httpx.post(
                f"{_GRAPH_URL}/{phone_number_id}/messages",
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    # Meta wants the number without the leading plus.
                    "to": to.lstrip("+"),
                    "type": "text",
                    "text": {"preview_url": False, "body": text},
                },
                timeout=_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            # The exception's own str() can carry the request URL, which
            # carries the phone number id but never the token -- that is
            # in a header. Still logged rather than raised onward, so what
            # reaches the client is only that the provider was unreachable.
            logger.warning("WhatsApp request failed: %s", type(exc).__name__)
            raise MessagingProviderError("the provider could not be reached") from exc

        if response.status_code >= 400:
            # Meta puts a reason in the body. It is worth logging and not
            # worth returning: it is written for whoever built the
            # integration, not for the agent who pressed send.
            logger.warning(
                "WhatsApp rejected a message: %s %s",
                response.status_code,
                response.text[:500],
            )
            raise MessagingProviderError(
                f"the provider rejected the message ({response.status_code})"
            )

        return SentMessage(external_message_id=_first_message_id(response.json()))

    def verify_signature(self, *, payload: bytes, signature_header: str) -> bool:
        """Whether this delivery was signed with the app secret.

        The signature covers the raw body, byte for byte, which is why the
        route hands over `await request.body()` rather than the parsed
        JSON: re-serialising it would change the bytes and the comparison
        would fail on every valid delivery.
        """
        secret = get_settings().whatsapp_app_secret

        if secret is None:
            # Refusing everything is the right answer for an unconfigured
            # secret. Accepting everything would make the endpoint an open
            # door for anybody who guessed the URL.
            logger.warning("A WhatsApp webhook arrived with no app secret configured")
            return False

        prefix, _, provided = signature_header.partition("=")

        if prefix != "sha256" or not provided:
            return False

        expected = hmac.new(
            secret.get_secret_value().encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()

        # Constant time: a byte-by-byte comparison that returns early
        # leaks, one character at a time, what the right signature was.
        return hmac.compare_digest(expected, provided)

    def parse_webhook(self, payload: dict[str, Any]) -> WebhookEvents:
        """Pull the messages and statuses out of Meta's envelope.

        Written to survive a payload that is not shaped as expected. A
        webhook is somebody else's data arriving unannounced, and the
        version of it that matters is the one sent the week Meta changes
        something: skipping what cannot be read beats a 500 that makes the
        provider retry the same unreadable delivery for a day.
        """
        messages: list[InboundMessage] = []
        statuses: list[StatusUpdate] = []
        phone_number_id: str | None = None

        for entry in _items(payload.get("entry")):
            for change in _items(entry.get("changes")):
                value = change.get("value")

                if not isinstance(value, dict):
                    continue

                metadata = value.get("metadata")

                if isinstance(metadata, dict):
                    found = metadata.get("phone_number_id")
                    phone_number_id = phone_number_id or (
                        found if isinstance(found, str) else None
                    )

                names = _profile_names(value)

                for raw in _items(value.get("messages")):
                    parsed = _inbound(raw, names)

                    if parsed is not None:
                        messages.append(parsed)

                for raw in _items(value.get("statuses")):
                    update = _status(raw)

                    if update is not None:
                        statuses.append(update)

        return WebhookEvents(
            external_phone_number_id=phone_number_id,
            messages=messages,
            statuses=statuses,
        )


def _items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, dict)]


def _profile_names(value: dict[str, Any]) -> dict[str, str]:
    """The display names Meta ships alongside, keyed by number."""
    names: dict[str, str] = {}

    for contact in _items(value.get("contacts")):
        wa_id = contact.get("wa_id")
        profile = contact.get("profile")

        if isinstance(wa_id, str) and isinstance(profile, dict):
            name = profile.get("name")

            if isinstance(name, str):
                names[wa_id] = name

    return names


def _inbound(
    raw: dict[str, Any],
    names: dict[str, str],
) -> InboundMessage | None:
    """One message, if it is a text one this MVP can carry.

    Images, audio and the interactive templates are skipped rather than
    stored empty. A row in a thread with no content is worse than a gap:
    an agent reads it as the customer having said nothing.
    """
    if raw.get("type") != "text":
        return None

    message_id = raw.get("id")
    sender = raw.get("from")
    body = raw.get("text")

    if not isinstance(message_id, str) or not isinstance(sender, str):
        return None

    if not isinstance(body, dict) or not isinstance(body.get("body"), str):
        return None

    return InboundMessage(
        external_message_id=message_id,
        # Meta sends a wa_id, which is E.164 without the plus.
        from_phone_number=f"+{sender.lstrip('+')}",
        text=body["body"],
        sent_at=_timestamp(raw.get("timestamp")),
        profile_name=names.get(sender),
    )


def _status(raw: dict[str, Any]) -> StatusUpdate | None:
    message_id = raw.get("id")
    name = raw.get("status")

    if not isinstance(message_id, str) or not isinstance(name, str):
        return None

    status = _STATUSES.get(name)

    if status is None:
        return None

    return StatusUpdate(
        external_message_id=message_id,
        status=status,
        occurred_at=_timestamp(raw.get("timestamp")),
    )


def _timestamp(value: Any) -> datetime:
    """Meta's seconds-since-epoch, as a string, defensively.

    Falls back to now rather than refusing the message. A message with a
    slightly wrong time is worth having; one dropped because its
    timestamp was unreadable is not.
    """
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError):
        return datetime.now(UTC)


def _first_message_id(body: Any) -> str:
    if isinstance(body, dict):
        for message in _items(body.get("messages")):
            found = message.get("id")

            if isinstance(found, str):
                return found

    raise MessagingProviderError("the provider accepted the message without an id")
