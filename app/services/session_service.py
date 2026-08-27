import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import (
    InactiveUserError,
    InvalidRefreshTokenError,
    RefreshTokenReusedError,
    SessionNotFoundError,
)
from app.core.security import generate_token, hash_token
from app.db.session import SessionDep
from app.models.user import User
from app.models.user_session import SessionEndReason, UserSession
from app.repositories.user_session_repository import UserSessionRepository

# A User-Agent header is whatever the client says it is, and some of them
# are long. Kept to what the column holds rather than refused: it is a
# label for a human to read, and a truncated one still says "Firefox on a
# Mac" where a rejected sign-in says nothing at all.
_USER_AGENT_LIMIT = 255


@dataclass(frozen=True)
class IssuedSession:
    """A live session and the one readable refresh token for it.

    The token exists in this form for exactly as long as it takes to put
    it in a response. What is stored is its digest, so nothing after this
    can reproduce it -- the same arrangement invitations use.
    """

    session: UserSession
    refresh_token: str


class SessionService:
    """Everything that starts, continues, or ends a sign-in.

    One owner for the whole lifecycle, because the rules only make sense
    together: rotation is what makes a stolen token expensive, reuse
    detection is what makes rotation worth doing, and revocation is what
    both of them feed into. Split across two services, the third one
    would eventually be written twice.

    AuthService turns what happens here into tokens; the account API
    turns it into a list somebody can act on. Neither knows how a chain
    works.
    """

    def __init__(self, session: Session, repository: UserSessionRepository) -> None:
        self._session = session
        self._repository = repository

    # --- starting and continuing -------------------------------------------

    def begin(
        self,
        user: User,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> IssuedSession:
        """Open a session for somebody whose credentials have been checked.

        Deliberately does not check them itself. Authentication is
        AuthService's job, and a method here that took a password would
        be a second way into the same decision.
        """
        now = datetime.now(UTC)

        session = self._repository.create(
            user_id=user.id,
            expires_at=now + self._idle_window(),
            user_agent=_trimmed(user_agent),
            ip_address=ip_address,
        )

        issued = self._issue(session)
        self._session.commit()

        return issued

    def rotate(self, refresh_token: str) -> tuple[IssuedSession, User]:
        """Spend a refresh token and hand back its successor.

        The order matters. The token is claimed before anything is
        issued, so if the claim loses -- because this token was already
        spent, or because another request spent it first -- nothing has
        been created that would have to be undone.
        """
        now = datetime.now(UTC)

        presented = self._repository.get_refresh_token(hash_token(refresh_token))

        if presented is None:
            raise InvalidRefreshTokenError

        session = self._repository.get_live_with_user(presented.session_id, now)

        if session is None:
            # The chain outlived its session, which only happens in the
            # gap between a session expiring and anything tidying up
            # after it. Nothing here is usable.
            raise InvalidRefreshTokenError

        user_session, user = session

        if not self._repository.claim(presented, at=now):
            # Somebody is holding a copy. Which somebody cannot be known
            # -- the legitimate client retrying a request whose response
            # it never saw looks identical from here -- so the session
            # goes rather than the benefit of the doubt.
            self._repository.revoke(
                user_session,
                at=now,
                reason=SessionEndReason.TOKEN_REUSED,
            )
            self._session.commit()

            raise RefreshTokenReusedError

        if not user.is_active:
            # Deactivated since the session started. Ends it, rather than
            # leaving a live chain attached to an account that is not
            # allowed to do anything with it.
            self._repository.revoke(
                user_session,
                at=now,
                reason=SessionEndReason.REVOKED,
            )
            self._session.commit()

            raise InactiveUserError(user.id)

        self._repository.touch(
            user_session,
            at=now,
            expires_at=now + self._idle_window(),
        )
        issued = self._issue(user_session)
        self._session.commit()

        return issued, user

    def resolve(self, session_id: uuid.UUID) -> tuple[UserSession, User] | None:
        """The session behind an access token, and who it belongs to.

        Runs on every authenticated request, which is what makes signing
        a device out take effect immediately rather than whenever its
        access token happened to run out.

        It costs nothing extra to do so. Authenticating already meant one
        query to load the user, and this is that query with a join and
        two more conditions on it.
        """
        return self._repository.get_live_with_user(session_id, datetime.now(UTC))

    # --- ending ------------------------------------------------------------

    def end(self, refresh_token: str) -> None:
        """Log out: revoke the session the presented token belongs to.

        Silent about whether the token meant anything, and idempotent. A
        client that has already thrown its tokens away should be able to
        call this and get on with showing a login screen, and a caller
        who guesses at a token should learn nothing from the answer.

        A spent token works here as well as a live one. Somebody holding
        an old link from a chain can therefore end the session, which is
        a nuisance and not a compromise -- and it is the same conclusion
        rotation already reaches when a spent token comes back.
        """
        presented = self._repository.get_refresh_token(hash_token(refresh_token))

        if presented is None:
            return

        session = self._repository.get(presented.session_id)

        if session is None or session.revoked_at is not None:
            return

        self._repository.revoke(
            session,
            at=datetime.now(UTC),
            reason=SessionEndReason.LOGGED_OUT,
        )
        self._session.commit()

    def list_for(self, user: User) -> Sequence[UserSession]:
        return self._repository.list_live_for_user(user.id, datetime.now(UTC))

    def revoke(self, user: User, session_id: uuid.UUID) -> UserSession:
        """End one session, named from the account's own list.

        Ending the current one is allowed. It is what "sign this device
        out" means when the device in hand is the one being tidied up
        from somewhere else, and refusing it would be second-guessing
        somebody about their own account.
        """
        now = datetime.now(UTC)
        session = self._repository.get_live_for_user(user.id, session_id, now)

        if session is None:
            raise SessionNotFoundError(user.id, session_id)

        revoked = self._repository.revoke(
            session,
            at=now,
            reason=SessionEndReason.REVOKED,
        )
        self._session.commit()

        return revoked

    def revoke_all(
        self,
        user: User,
        *,
        reason: SessionEndReason = SessionEndReason.REVOKED,
        keep: uuid.UUID | None = None,
    ) -> int:
        """Sign the account out, optionally sparing one session.

        `keep` is what makes changing a password sign out every other
        device without signing out the person doing it. Left unset this
        is "sign out everywhere", the caller's own session included --
        which is what the button of that name is for.
        """
        now = datetime.now(UTC)

        ended = self._repository.revoke_live_for_user(
            user.id,
            at=now,
            reason=reason,
            keep=keep,
        )
        self._session.commit()

        return ended

    # --- shared ------------------------------------------------------------

    def _issue(self, session: UserSession) -> IssuedSession:
        # The only moment the token exists in readable form.
        token = generate_token()

        self._repository.issue(session_id=session.id, token_hash=hash_token(token))

        return IssuedSession(session=session, refresh_token=token)

    def _idle_window(self) -> timedelta:
        return timedelta(days=get_settings().refresh_token_expire_days)


def _trimmed(user_agent: str | None) -> str | None:
    if user_agent is None:
        return None

    return user_agent[:_USER_AGENT_LIMIT] or None


def get_user_session_repository(session: SessionDep) -> UserSessionRepository:
    return UserSessionRepository(session)


UserSessionRepositoryDep = Annotated[
    UserSessionRepository,
    Depends(get_user_session_repository),
]


def get_session_service(
    session: SessionDep,
    repository: UserSessionRepositoryDep,
) -> SessionService:
    return SessionService(session=session, repository=repository)


SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]
