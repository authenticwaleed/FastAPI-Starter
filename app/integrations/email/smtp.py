import logging
import smtplib
from collections.abc import Callable
from email.message import EmailMessage as MimeMessage

from app.core.exceptions import EmailDeliveryError
from app.integrations.email.base import EmailMessage

logger = logging.getLogger(__name__)

# How a connection is opened. Injected rather than called directly so a
# test can hand over something that records instead of dialling: the part
# worth testing here is the message that gets built and what happens when
# the server refuses, and neither of those needs a socket.
Connect = Callable[[], smtplib.SMTP]


class SmtpEmailSender:
    """Sends mail over SMTP, using nothing but the standard library.

    Blocking, like every other outbound call in this application, and
    called from a background task for that reason: a mail server that
    takes ten seconds to answer must not be ten seconds a person waits
    for their password reset form to submit.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        sender: str,
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = True,
        connect: Connect | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._sender = sender
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._connect = connect or self._dial

    def send(self, message: EmailMessage) -> None:
        mime = MimeMessage()
        mime["From"] = self._sender
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.set_content(message.body)

        try:
            with self._connect() as server:
                if self._use_tls:
                    server.starttls()

                if self._username is not None and self._password is not None:
                    server.login(self._username, self._password)

                server.send_message(mime)
        except (smtplib.SMTPException, OSError) as exc:
            # Whatever the server said goes to the log. What the caller
            # gets is that it did not go, because an SMTP response code is
            # written for whoever configured the mail server.
            logger.warning("SMTP delivery to %s failed: %s", message.to, exc)

            raise EmailDeliveryError(f"SMTP delivery failed: {exc}") from exc

    def _dial(self) -> smtplib.SMTP:
        return smtplib.SMTP(self._host, self._port, timeout=10)
