"""The two messages this application sends, and the links inside them.

Kept together, and kept out of the service that decides *whether* to send
them, for the reason prompts.py is its own module: wording is the part
that gets edited most often and understood least by the code around it.

Plain text, deliberately. Both are a sentence and a link.
"""

from app.core.config import get_settings
from app.integrations.email.base import EmailMessage

# The dashboard's routes, not this API's. A person clicking a link in
# their mail expects a page, and the page is what calls the endpoint.
VERIFY_EMAIL_PATH = "/verify-email"
RESET_PASSWORD_PATH = "/reset-password"  # noqa: S105  (a URL path, not a secret)


def _link(path: str, token: str) -> str:
    """The URL to put in front of somebody, or the bare token.

    With no frontend configured there is no page to send anyone to, so
    the token goes in on its own. That is a developer reading their own
    log, which is the only situation the setting is allowed to be unset
    in -- production refuses to start without it.
    """
    base = get_settings().frontend_base_url

    if base is None:
        return token

    return f"{base.rstrip('/')}{path}?token={token}"


def verification_email(*, to: str, token: str) -> EmailMessage:
    return EmailMessage(
        to=to,
        subject="Confirm your email address",
        body=(
            "Confirm this address to finish setting up your account:\n\n"
            f"{_link(VERIFY_EMAIL_PATH, token)}\n\n"
            "If you did not create an account, you can ignore this message "
            "and nothing will happen."
        ),
    )


def password_reset_email(
    *, to: str, token: str, valid_for_minutes: int
) -> EmailMessage:
    return EmailMessage(
        to=to,
        subject="Reset your password",
        body=(
            "Somebody asked to reset the password on this account. "
            f"This link works once, and for the next {valid_for_minutes} "
            "minutes:\n\n"
            f"{_link(RESET_PASSWORD_PATH, token)}\n\n"
            "If that was not you, ignore this message. Your password has "
            "not changed, and nobody can change it without this link."
        ),
    )
