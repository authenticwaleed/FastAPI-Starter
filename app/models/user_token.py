import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column


class UserTokenPurpose(StrEnum):
    """What the link this token stands for is allowed to do.

    Both flows are the same act -- prove you are reading mail at this
    address -- with different consequences, which is why they share a
    table. The purpose is what stops a verification link, the cheap one
    with the long life, from being spent as a password reset.
    """

    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"  # noqa: S105  (a purpose, not a secret)


class UserToken(Base):
    """A single-use secret mailed to an address, with an expiry.

    Deliberately not the same table as workspace_invitations, which it
    resembles. An invitation is an offer to somebody who may not have an
    account; this is a challenge to somebody who does, and the row it
    hangs off is the user rather than the workspace.

    Like an invitation it has no status column: used, expired or live is
    a function of two timestamps and the clock.
    """

    __tablename__ = "user_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    purpose: Mapped[UserTokenPurpose] = mapped_column(
        enum_column(UserTokenPurpose, name="user_token_purpose"),
        index=True,
    )

    # The address this was actually sent to, lowercased, rather than
    # "whatever the account's address is now". A token proves control of
    # one mailbox, and without this a link mailed to an old address would
    # still work after the account moved to a new one -- confirming an
    # address nobody ever received mail at, or resetting a password on
    # the strength of a message the new owner never saw.
    email: Mapped[str] = mapped_column(String(320))

    # The hash, never the token. Same rule and same reason as
    # workspace_invitations: a leaked table must not be a set of working
    # links. Unique so resolving one is a single indexed lookup.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # Null until spent. Set once, inside the same transaction as whatever
    # the link did, which is what makes it single-use rather than
    # single-use-unless-two-requests-arrive-together.
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    def is_usable_at(self, now: datetime) -> bool:
        return self.used_at is None and self.expires_at > now

    def __repr__(self) -> str:
        return f"UserToken(id={self.id!r}, purpose={self.purpose!r})"
