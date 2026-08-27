from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from jwt import InvalidTokenError

from app.core.exceptions import InactiveUserError, InvalidCredentialsError
from app.core.security import (
    access_token_lifetime,
    create_access_token,
    decode_access_token,
    unusable_hash,
    verify_password,
)
from app.models.user import User
from app.models.user_session import UserSession
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, TokenPair
from app.schemas.user import UserCreate
from app.services.session_service import (
    IssuedSession,
    SessionService,
    SessionServiceDep,
)
from app.services.user_service import (
    UserRepositoryDep,
    UserService,
    UserServiceDep,
)


@dataclass(frozen=True)
class Authenticated:
    """Who is making this request, and from which sign-in.

    Both, because a request now belongs to a session as well as to a
    person: most routes only want the user, and the ones that manage
    sessions need to know which row is "this device".
    """

    user: User
    session: UserSession


class AuthService:
    """Registration, login, and answering "who does this token belong to?".

    Password hashing and the unique-email rule stay in UserService; the
    session lifecycle stays in SessionService. What this service owns is
    the credential check and the tokens -- the translation between "these
    are the right credentials" and "here is something to send with the
    next request".
    """

    def __init__(
        self,
        users: UserService,
        repository: UserRepository,
        sessions: SessionService,
    ) -> None:
        self._users = users
        self._repository = repository
        self._sessions = sessions

    def register(self, payload: UserCreate) -> User:
        # Registration is user creation. Delegating keeps one place that
        # hashes the password and enforces the unique email, rather than a
        # second path that could drift from it.
        return self._users.create_user(payload)

    def authenticate(self, email: str, password: str) -> User:
        user = self._repository.get_by_email(email)

        if user is None:
            # Verify against a hash nothing matches. Returning early here
            # instead would make an unknown address measurably faster than a
            # wrong password, which is enough to enumerate accounts.
            verify_password(password, unusable_hash())
            raise InvalidCredentialsError

        if not verify_password(password, user.hashed_password):
            raise InvalidCredentialsError

        if not user.is_active:
            raise InactiveUserError(user.id)

        return user

    def login(
        self,
        credentials: LoginRequest,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        """Check credentials, open a session, and hand back both tokens.

        Every login opens a new session rather than reusing one. Two
        browsers are two sessions, which is what makes signing one of
        them out mean anything.
        """
        user = self.authenticate(credentials.email, credentials.password)

        issued = self._sessions.begin(
            user,
            user_agent=user_agent,
            ip_address=ip_address,
        )

        return self._pair(user, issued)

    def refresh(self, refresh_token: str) -> TokenPair:
        """Trade the refresh token for a new pair.

        Both halves are replaced. Returning the same refresh token would
        make it long-lived again and undo the point of rotating it, so a
        client has to store what comes back here.
        """
        issued, user = self._sessions.rotate(refresh_token)

        return self._pair(user, issued)

    def logout(self, refresh_token: str) -> None:
        self._sessions.end(refresh_token)

    def authenticate_token(self, token: str) -> Authenticated:
        """Resolve an access token into the caller and their session.

        Three things have to hold, and they fail differently on purpose.
        A token that does not decode, or whose session has been revoked
        or has lapsed, is a 401 -- the holder is not signed in. An
        account that has been deactivated is a 403 -- they are signed in,
        and the answer is still no.
        """
        try:
            claims = decode_access_token(token)
            user_id = int(claims.subject)
        except (InvalidTokenError, ValueError):
            raise InvalidCredentialsError(
                detail="Invalid or expired token",
            ) from None

        resolved = self._sessions.resolve(claims.session_id)

        if resolved is None:
            # No such session, or one that has been signed out, expired,
            # or belonged to an account that has since been deleted --
            # the row goes with the user. The token outlives all four.
            raise InvalidCredentialsError(detail="Invalid or expired token")

        session, user = resolved

        if user.id != user_id:
            # The two claims disagree. Nothing this application signs
            # looks like that, so the token is not one of ours however
            # well it verifies.
            raise InvalidCredentialsError(detail="Invalid or expired token")

        if not user.is_active:
            raise InactiveUserError(user.id)

        return Authenticated(user=user, session=session)

    def _pair(self, user: User, issued: IssuedSession) -> TokenPair:
        # The subject is the id rather than the email, so changing an
        # address does not invalidate live tokens and the token carries no
        # personal data for whoever ends up holding it.
        return TokenPair(
            access_token=create_access_token(
                str(user.id),
                session_id=issued.session.id,
            ),
            refresh_token=issued.refresh_token,
            expires_in=int(access_token_lifetime().total_seconds()),
        )


def get_auth_service(
    users: UserServiceDep,
    repository: UserRepositoryDep,
    sessions: SessionServiceDep,
) -> AuthService:
    return AuthService(users=users, repository=repository, sessions=sessions)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
