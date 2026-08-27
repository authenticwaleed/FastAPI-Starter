"""The two senders, without a mail server anywhere in sight.

The SMTP adapter's connection is injectable for exactly this: the parts
worth checking are the message it builds and what it does when the server
refuses, and neither of those needs a socket.
"""

import logging
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage as MimeMessage
from types import TracebackType

import pytest

from app.core.exceptions import EmailDeliveryError
from app.integrations.email.base import EmailMessage
from app.integrations.email.log import LoggingEmailSender
from app.integrations.email.smtp import SmtpEmailSender

MESSAGE = EmailMessage(
    to="ada@example.com",
    subject="Reset your password",
    body="Follow this link: https://app.example.com/reset-password?token=abc",
)


@dataclass
class FakeSmtp:
    """Records what a real smtplib.SMTP would have been asked to do."""

    started_tls: bool = False
    logged_in_as: str | None = None
    messages: list[MimeMessage] = field(default_factory=list)
    fail_with: Exception | None = None

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, username: str, password: str) -> None:
        self.logged_in_as = username

    def send_message(self, message: MimeMessage) -> None:
        if self.fail_with is not None:
            raise self.fail_with

        self.messages.append(message)


def _sender(server: FakeSmtp, **kwargs: object) -> SmtpEmailSender:
    return SmtpEmailSender(
        host="smtp.example.com",
        port=587,
        sender="no-reply@example.com",
        connect=lambda: server,  # type: ignore[arg-type,return-value]
        **kwargs,  # type: ignore[arg-type]
    )


def test_the_message_carries_the_addresses_and_the_body() -> None:
    server = FakeSmtp()

    _sender(server).send(MESSAGE)

    sent = server.messages[0]
    assert sent["From"] == "no-reply@example.com"
    assert sent["To"] == "ada@example.com"
    assert sent["Subject"] == "Reset your password"
    assert MESSAGE.body in sent.get_content()


def test_tls_is_started_by_default() -> None:
    server = FakeSmtp()

    _sender(server).send(MESSAGE)

    assert server.started_tls is True


def test_tls_can_be_turned_off_for_a_local_mail_trap() -> None:
    server = FakeSmtp()

    _sender(server, use_tls=False).send(MESSAGE)

    assert server.started_tls is False


def test_credentials_are_used_when_there_are_any() -> None:
    server = FakeSmtp()

    _sender(server, username="ada", password="hunter2").send(MESSAGE)

    assert server.logged_in_as == "ada"


def test_no_login_is_attempted_without_credentials() -> None:
    server = FakeSmtp()

    _sender(server).send(MESSAGE)

    assert server.logged_in_as is None


def test_a_refusal_becomes_a_delivery_error() -> None:
    # Whatever the server said belongs in the log; what the caller gets
    # is that it did not go.
    server = FakeSmtp(fail_with=smtplib.SMTPRecipientsRefused({}))

    with pytest.raises(EmailDeliveryError):
        _sender(server).send(MESSAGE)


def test_an_unreachable_server_becomes_a_delivery_error() -> None:
    server = FakeSmtp(fail_with=OSError("connection refused"))

    with pytest.raises(EmailDeliveryError):
        _sender(server).send(MESSAGE)


def test_the_logging_sender_writes_the_whole_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Which is the reason production refuses to start without a real one.
    with caplog.at_level(logging.INFO):
        LoggingEmailSender().send(MESSAGE)

    assert MESSAGE.to in caplog.text
    assert MESSAGE.body in caplog.text
