from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.models.message import MessageStatus


@dataclass(frozen=True)
class SentMessage:
    """What a provider gives back when it accepts a message.

    The id is the whole point: it is what a later status notification
    refers to, so without it a message can never be told apart from
    another and `delivered` has nothing to attach to.
    """

    external_message_id: str


@dataclass(frozen=True)
class InboundMessage:
    """A customer's message, in this application's vocabulary.

    Provider-shaped fields stop here. Everything downstream -- finding the
    contact, opening the conversation, writing the row -- works from this,
    which is what lets a second provider be added without touching any of
    it.
    """

    external_message_id: str
    from_phone_number: str
    text: str
    sent_at: datetime
    # The name the customer set on their own WhatsApp profile, when the
    # provider passes it along. Useful, and not to be trusted as identity.
    profile_name: str | None = None


@dataclass(frozen=True)
class StatusUpdate:
    """A provider saying what became of a message it took earlier."""

    external_message_id: str
    status: MessageStatus
    occurred_at: datetime


@dataclass(frozen=True)
class WebhookEvents:
    """Everything one webhook delivery carried, already sorted by kind.

    A single delivery can hold several messages and several status
    updates, which is exactly why ingestion has to be idempotent: the
    provider will resend the whole envelope if any part of handling it
    fails.
    """

    # The provider's own id for the number the delivery is about, which is
    # how a delivery is matched to the workspace that connected it.
    external_phone_number_id: str | None = None
    messages: list[InboundMessage] = field(default_factory=list)
    statuses: list[StatusUpdate] = field(default_factory=list)


class MessagingProvider(Protocol):
    """What the application needs a messaging provider to do.

    A Protocol rather than a base class: the fake used in tests is not a
    WhatsApp client with pieces removed, it is a different object that
    answers the same three questions, and inheritance would only make it
    pretend otherwise.
    """

    def send_text(
        self,
        *,
        phone_number_id: str,
        access_token: str,
        to: str,
        text: str,
    ) -> SentMessage:
        """Hand a message to the provider, or raise MessagingProviderError."""
        ...

    def verify_signature(self, *, payload: bytes, signature_header: str) -> bool:
        """Whether this delivery really came from the provider."""
        ...

    def parse_webhook(self, payload: dict[str, Any]) -> WebhookEvents:
        """Turn one delivery into messages and status updates."""
        ...
