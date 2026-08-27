import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column


class SessionEndReason(StrEnum):
    """Why a session stopped working.

    Recorded because "I was signed out and I do not know why" is the
    support ticket this column answers. It is only ever set alongside
    `revoked_at`; a session that simply expired has neither.
    """

    LOGGED_OUT = "logged_out"
    # Ended from the session list, by the person who owns the account.
    REVOKED = "revoked"
    PASSWORD_CHANGED = "password_changed"  # noqa: S105  (a reason, not a secret)
    # A refresh token came back after it had already been exchanged. See
    # UserSession's note below: that is the signal the chain was copied.
    TOKEN_REUSED = "token_reused"  # noqa: S105  (a reason, not a secret)


class UserSession(Base):
    """One sign-in: a browser or a device the account currently trusts.

    A session is the unit the product speaks about -- "you are signed in
    on three devices, sign this one out" -- and the unit revocation acts
    on. The secrets that keep it alive are the RefreshToken rows below;
    this row is what a person sees and what a check consults.

    It has no status column, for the reason WorkspaceInvitation has none:
    the state is a function of two timestamps and the clock, and storing
    it as well would be a third thing that could disagree with them.

    `expires_at` slides. Every rotation pushes it out again, so the
    setting behind it is an idle timeout: a session dies when nobody has
    used it for that long, not on a fixed date the person cannot see
    coming.
    """

    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    # What the session list shows so somebody can recognise a device they
    # do not remember using. Both are best effort -- a header anyone can
    # set, and an address that a proxy may have rewritten -- so neither is
    # ever used to decide anything. They are there to be read by a human.
    user_agent: Mapped[str | None] = mapped_column(String(255), default=None)
    # 45 characters is the longest an IPv6 address gets, including the
    # IPv4-mapped form.
    ip_address: Mapped[str | None] = mapped_column(String(45), default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # Moved forward on every rotation, which is roughly every time the
    # access token runs out -- so "last active" is accurate to about the
    # access token's lifetime. Deliberately not written on every request:
    # an UPDATE per API call would turn a read into a write.
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # Kept alongside `last_used_at` rather than derived from it. A row
    # that carries its own expiry says when it dies without anyone having
    # to know what the application was configured with at the time, and a
    # change to that setting cannot silently lengthen sessions already
    # issued.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

    revoked_reason: Mapped[SessionEndReason | None] = mapped_column(
        enum_column(SessionEndReason, name="session_revoked_reason"),
        default=None,
    )

    def is_live_at(self, now: datetime) -> bool:
        """Whether this session still authorises anything, as of `now`.

        The clock is passed in rather than read here, for the reason
        WorkspaceInvitation passes it: a test should be able to ask what
        a session looks like next month without waiting for next month.
        """
        return self.revoked_at is None and self.expires_at > now

    def __repr__(self) -> str:
        return f"UserSession(id={self.id!r}, user_id={self.user_id!r})"


class RefreshToken(Base):
    """One link in a session's chain of refresh secrets.

    Every refresh mints a new one and marks the old one used, so a
    session is a chain rather than a single long-lived key. Two things
    fall out of that, and both are the point:

    A token that has been exchanged is worthless -- there is exactly one
    live link at the end of the chain, and it is the only one a refresh
    will accept.

    A token that has been exchanged arriving *again* is evidence. The
    legitimate client moved on to the next link, so whoever is holding
    this one either copied it or is the client working from a copy that
    was taken. Neither can be told from the other, so the whole session
    is revoked rather than guessed about. That is the reason spent links
    are kept at all: a chain that only remembered its current token could
    not tell a stolen one from a token that never existed.

    Kept only while the session lives. Revoking a session deletes its
    chain, because once the session is dead no token in it can do
    anything, and a dead chain answers no question worth asking.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_sessions.id", ondelete="CASCADE"),
        index=True,
    )

    # The hash, never the token -- the same rule the invitation table
    # follows, and for a sharper reason: a leaked backup of this table
    # would otherwise be a set of live logins. Unique so that resolving a
    # presented token is one indexed lookup, which an unsalted SHA-256
    # digest is what makes possible. See `hash_token`.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)

    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # Null while this is the live link. Set once, by a conditional UPDATE,
    # which is what makes exchanging it atomic: two requests racing the
    # same token cannot both come away with a new one.
    rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

    # No expiry of its own. A refresh token is usable exactly while it is
    # the un-rotated link of a live session, so the session's `expires_at`
    # is the one place a lifetime is written down.

    def __repr__(self) -> str:
        return f"RefreshToken(id={self.id!r}, session_id={self.session_id!r})"
