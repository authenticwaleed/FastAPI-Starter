from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EmailMessage:
    """One message, as this application thinks of one.

    Plain text and nothing else. The two emails sent here are a sentence
    and a link, HTML would double the surface for no gain, and a message
    that renders identically in every client is worth more than one that
    looks designed in some of them.
    """

    to: str
    subject: str
    body: str


class EmailSender(Protocol):
    """What the application needs of whatever delivers its mail.

    A Protocol rather than a base class, for the reason MessagingProvider
    is one: the sender used in tests is not an SMTP client with pieces
    removed, it is a different object answering the same question.
    """

    def send(self, message: EmailMessage) -> None:
        """Deliver it, or raise EmailDeliveryError."""
        ...
