"""Sending the two auth emails after the response has already gone.

Two reasons, and the enumeration one is the reason this is not simply an
inline call.

A request that asks "send a reset link to this address" must take the same
time whether or not the address belongs to anybody. Done inline, it
cannot: the real case reaches a mail server and the unknown one returns
after a single indexed SELECT, and the difference is large enough to read
off a stopwatch. Scheduling the whole thing -- the lookup, the token, the
send -- leaves the handler doing nothing but parsing a body, so there is
nothing left to measure.

The second reason is the ordinary one: an SMTP server that takes ten
seconds to answer must not be ten seconds somebody waits on a form.

The session comes from the same source ai_dispatch uses, and for the same
reason -- a dependency that yields is torn down before the response is
sent, so a background task holding the request's session is holding a
closed one.
"""

import logging
from collections.abc import Callable
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.integrations.email.base import EmailMessage, EmailSender
from app.integrations.email.log import LoggingEmailSender
from app.integrations.email.smtp import SmtpEmailSender
from app.repositories.user_repository import UserRepository
from app.repositories.user_session_repository import UserSessionRepository
from app.repositories.user_token_repository import UserTokenRepository
from app.services.ai_dispatch import SessionSource, open_session
from app.services.session_service import SessionService
from app.services.user_service import UserService
from app.services.verification_service import VerificationService

logger = logging.getLogger(__name__)

# Which of the service's two request methods to run. Both have this
# shape, and passing the unbound method keeps the choice at the call site
# where the name of the email already is.
MessageBuilder = Callable[[VerificationService, str], EmailMessage | None]


@lru_cache
def get_email_sender() -> EmailSender:
    """Whatever delivers mail here, as a dependency.

    A dependency and not an import, so a test substitutes a sender that
    records instead of patching a module. Cached because the adapter
    holds only configuration.

    With no SMTP host it writes the message to the log instead. That is a
    laptop, where there is no mail server and the person who needs to
    read the link is the developer who just registered -- and it is why
    the settings refuse to start production without one, rather than
    quietly falling through to here.
    """
    settings = get_settings()

    if settings.smtp_host is None or settings.email_from is None:
        return LoggingEmailSender()

    password = settings.smtp_password

    return SmtpEmailSender(
        host=settings.smtp_host,
        port=settings.smtp_port,
        sender=settings.email_from,
        username=settings.smtp_username,
        password=password.get_secret_value() if password is not None else None,
        use_tls=settings.smtp_use_tls,
    )


EmailSenderDep = Annotated[EmailSender, Depends(get_email_sender)]


def build_verification_service(session: Session) -> VerificationService:
    """The same graph FastAPI assembles, written out for a run of its own."""
    repository = UserRepository(session)

    return VerificationService(
        session=session,
        tokens=UserTokenRepository(session),
        users=UserService(session=session, repository=repository),
        repository=repository,
        sessions=SessionService(
            session=session,
            repository=UserSessionRepository(session),
        ),
    )


def send_verification_email(
    *,
    email: str,
    sender: EmailSender,
    session_source: SessionSource = open_session,
) -> None:
    """Ask somebody to confirm the address they registered with.

    Does nothing at all for an address with nothing to confirm. Whether
    that happened is not reported anywhere a caller can see -- see the
    module docstring.
    """
    _dispatch(
        kind="verification",
        email=email,
        sender=sender,
        session_source=session_source,
        build=VerificationService.verification_email_for,
    )


def send_password_reset_email(
    *,
    email: str,
    sender: EmailSender,
    session_source: SessionSource = open_session,
) -> None:
    """Send a reset link, if this address has an account to reset."""
    _dispatch(
        kind="password reset",
        email=email,
        sender=sender,
        session_source=session_source,
        build=VerificationService.reset_email_for,
    )


def _dispatch(
    *,
    kind: str,
    email: str,
    sender: EmailSender,
    session_source: SessionSource,
    build: MessageBuilder,
) -> None:
    """Issue the token and hand the message over, swallowing everything.

    This runs after its response, so there is nobody left to tell. An
    exception escaping here would be logged as an unhandled error in a
    request that succeeded, which is a worse account of what happened
    than the line below.

    The address is never logged. A log line naming who asked for a reset
    is a log line saying that person has an account here.
    """
    try:
        with session_source() as session:
            message = build(build_verification_service(session), email)

            if message is None:
                logger.info("No %s email to send", kind)
                return

            sender.send(message)
            logger.info("Sent a %s email", kind)
    except AppError as exc:
        logger.warning("A %s email was not sent: %s", kind, exc)
    except Exception:
        logger.exception("A %s email failed", kind)
