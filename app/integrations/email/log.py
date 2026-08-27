import logging

from app.integrations.email.base import EmailMessage

logger = logging.getLogger(__name__)


class LoggingEmailSender:
    """Writes the message to the log instead of sending it.

    What runs on a laptop, where there is no mail server and the person
    who needs to read the verification link is the developer who just
    registered. The whole body is logged, link included, which is exactly
    why the settings refuse to start production without a real sender:
    this is a reset link in a log file, and that is only acceptable when
    the account it belongs to is one somebody invented thirty seconds ago.
    """

    def send(self, message: EmailMessage) -> None:
        logger.info(
            "Email not sent, no SMTP host configured. To: %s\nSubject: %s\n\n%s",
            message.to,
            message.subject,
            message.body,
        )
