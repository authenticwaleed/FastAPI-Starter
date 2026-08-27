"""A messaging provider that records instead of calling anybody.

Substituted for the real adapter wherever a test needs to know what would
have been sent, or to decide what the provider says back. No test in this
suite reaches the network.
"""

from dataclasses import dataclass, field
from typing import Any

from app.core.exceptions import MessagingProviderError
from app.integrations.messaging.base import SentMessage, WebhookEvents
from app.integrations.messaging.whatsapp import WhatsAppCloudProvider


@dataclass
class SendAttempt:
    phone_number_id: str
    access_token: str
    to: str
    text: str


@dataclass
class FakeMessagingProvider:
    """Records what it was asked to send, and answers however told to.

    `parse_webhook` is delegated to the real adapter on purpose: parsing
    Meta's envelope is the part most worth testing against the code that
    will actually run, and it is pure -- it reaches nothing.
    """

    sent: list[SendAttempt] = field(default_factory=list)
    next_message_id: str = "wamid.FAKE"
    fail_with: str | None = None
    signature_is_valid: bool = True

    def send_text(
        self,
        *,
        phone_number_id: str,
        access_token: str,
        to: str,
        text: str,
    ) -> SentMessage:
        self.sent.append(
            SendAttempt(
                phone_number_id=phone_number_id,
                access_token=access_token,
                to=to,
                text=text,
            )
        )

        if self.fail_with is not None:
            raise MessagingProviderError(self.fail_with)

        return SentMessage(external_message_id=self.next_message_id)

    def verify_signature(self, *, payload: bytes, signature_header: str) -> bool:
        return self.signature_is_valid

    def parse_webhook(self, payload: dict[str, Any]) -> WebhookEvents:
        return WhatsAppCloudProvider().parse_webhook(payload)
