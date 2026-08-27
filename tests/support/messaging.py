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

    `parse_webhook` and `verify_signature` are delegated to the real
    adapter on purpose: parsing Meta's envelope and checking its HMAC are
    the parts most worth testing against the code that will actually run,
    and both are pure -- they reach nothing. Only `send_text` is faked,
    because only `send_text` calls anybody.
    """

    sent: list[SendAttempt] = field(default_factory=list)
    # Returned verbatim, and reused across sends on purpose. A workspace's
    # provider ids are unique, so a test that sends twice without changing
    # this hits the constraint that enforces it -- which is a signal worth
    # keeping: that is exactly how a double-send bug announces itself.
    next_message_id: str = "wamid.FAKE"
    fail_with: str | None = None
    # None means "ask the real adapter", which is the default because
    # verifying a signature is pure and reaches nobody -- so there is no
    # reason for the suite to check a fake copy of it. Set it to force an
    # answer when the test is about what happens next rather than about
    # the signature itself.
    signature_is_valid: bool | None = None

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
        if self.signature_is_valid is not None:
            return self.signature_is_valid

        return WhatsAppCloudProvider().verify_signature(
            payload=payload,
            signature_header=signature_header,
        )

    def parse_webhook(self, payload: dict[str, Any]) -> WebhookEvents:
        return WhatsAppCloudProvider().parse_webhook(payload)
