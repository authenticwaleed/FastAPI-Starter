"""An email sender that records instead of delivering.

Substituted wherever a test needs to read the link that would have been
sent, which is most of what the verification and reset flows are. No test
in this suite reaches a mail server.
"""

from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

from app.core.exceptions import EmailDeliveryError
from app.integrations.email.base import EmailMessage


@dataclass
class FakeEmailSender:
    """Keeps every message, and fails on demand."""

    sent: list[EmailMessage] = field(default_factory=list)
    fail_with: str | None = None

    def send(self, message: EmailMessage) -> None:
        self.sent.append(message)

        if self.fail_with is not None:
            raise EmailDeliveryError(self.fail_with)

    # --- reading what was sent -------------------------------------------

    @property
    def last(self) -> EmailMessage:
        assert self.sent, "no email was sent"

        return self.sent[-1]

    def token_in(self, message: EmailMessage) -> str:
        """The token out of the link, or the bare token if there is no link.

        Pulled out of the body the way a person would, rather than
        returned separately by the fake. What a test then asserts on is
        the value that actually reached the mailbox -- so a bug that
        emails the wrong token cannot pass.
        """
        line = next(
            part
            for part in message.body.split()
            if part.startswith("http") or _looks_like_a_token(part)
        )

        if not line.startswith("http"):
            return line

        return parse_qs(urlparse(line).query)["token"][0]

    @property
    def last_token(self) -> str:
        return self.token_in(self.last)


def _looks_like_a_token(part: str) -> bool:
    # 32 bytes of urlsafe base64 is 43 characters, and nothing else in
    # either message body is anywhere near that long without a space.
    return len(part) >= 43 and " " not in part
