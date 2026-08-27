from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import InvalidVerificationTokenError
from app.core.security import generate_token, hash_token
from app.db.session import SessionDep
from app.integrations.email.base import EmailMessage
from app.models.user import User
from app.models.user_session import SessionEndReason
from app.models.user_token import UserToken, UserTokenPurpose
from app.repositories.user_repository import UserRepository
from app.repositories.user_token_repository import UserTokenRepository
from app.schemas.user import UserUpdate
from app.services.emails import password_reset_email, verification_email
from app.services.session_service import SessionService, SessionServiceDep
from app.services.user_service import (
    UserRepositoryDep,
    UserService,
    UserServiceDep,
)


class VerificationService:
    """Confirming an address, and getting back in without a password.

    One service for both, because they are one act with two consequences:
    somebody proves they are reading mail at an address, and either the
    address is marked confirmed or the password behind it is replaced.
    The token mechanics -- issued once, hashed at rest, single-use, aged
    out, tied to the address it was sent to -- are identical, and written
    once here rather than twice.

    Nothing in this service tells a caller whether an address belongs to
    an account. The two request methods return a message to send or
    nothing at all, and the route answers the same way either way.
    """

    def __init__(
        self,
        session: Session,
        tokens: UserTokenRepository,
        users: UserService,
        repository: UserRepository,
        sessions: SessionService,
    ) -> None:
        self._session = session
        self._tokens = tokens
        self._users = users
        self._repository = repository
        self._sessions = sessions

    # --- asking -------------------------------------------------------

    def verification_email_for(self, email: str) -> EmailMessage | None:
        """The message to send, if this address has anything to confirm.

        None for an address nobody has registered, one that is already
        confirmed, and one on a deactivated account. All three are the
        same silence: the caller is unauthenticated, and an endpoint that
        behaved differently for a real address would answer "does this
        person have an account here?" to anybody who asked.
        """
        user = self._repository.get_by_email(email)

        if user is None or not user.is_active or user.email_verified_at is not None:
            return None

        token = self._issue(
            user,
            UserTokenPurpose.EMAIL_VERIFICATION,
            timedelta(hours=get_settings().email_verification_expire_hours),
        )

        return verification_email(to=user.email, token=token)

    def reset_email_for(self, email: str) -> EmailMessage | None:
        """The message to send, if this address can have its password reset.

        None for an unknown address and for a deactivated account, and
        silent about which -- see above. A confirmed address is not
        required: somebody who never got round to confirming can still
        forget their password, and refusing them would leave the account
        with no way back in at all.
        """
        user = self._repository.get_by_email(email)

        if user is None or not user.is_active:
            return None

        minutes = get_settings().password_reset_expire_minutes
        token = self._issue(
            user,
            UserTokenPurpose.PASSWORD_RESET,
            timedelta(minutes=minutes),
        )

        return password_reset_email(
            to=user.email,
            token=token,
            valid_for_minutes=minutes,
        )

    # --- answering ----------------------------------------------------

    def verify_email(self, token: str) -> User:
        used, user = self._usable(token, UserTokenPurpose.EMAIL_VERIFICATION)
        now = datetime.now(UTC)

        # Both flush; the commit below covers the pair. Marking the token
        # spent has to land with what it bought, or a link that failed
        # halfway would be a link that still works.
        self._tokens.mark_used(used, now)
        self._repository.mark_email_verified(user, now)
        self._session.commit()

        return user

    def reset_password(self, token: str, new_password: str) -> User:
        """Replace the password, and shut everything else out.

        Every session goes, with no exception for the caller: whoever is
        doing this arrived from a mailbox rather than from a signed-in
        screen, so there is no session of theirs to keep -- and if the
        reason they are here is that somebody else got in, that
        somebody's session is exactly what has to stop working.
        """
        used, user = self._usable(token, UserTokenPurpose.PASSWORD_RESET)
        now = datetime.now(UTC)

        # Before the password, for the reason AccountService.change_password
        # gives: this and the update below are two transactions, and of the
        # two orders only this one fails safely.
        self._sessions.revoke_all(user, reason=SessionEndReason.PASSWORD_CHANGED)

        self._tokens.mark_used(used, now)

        # They just proved they read mail at this address, which is the
        # same thing a verification link proves. Leaving it unconfirmed
        # after that would be the record disagreeing with what happened.
        if user.email_verified_at is None:
            self._repository.mark_email_verified(user, now)

        # Commits all three, because every repository above only flushed
        # and they all share this session. A failure here rolls the token
        # back to unused, which is the right way round: the link is worth
        # more than the attempt.
        return self._users.update_user(user.id, UserUpdate(password=new_password))

    # --- shared -------------------------------------------------------

    def _issue(
        self,
        user: User,
        purpose: UserTokenPurpose,
        lifetime: timedelta,
    ) -> str:
        # Anything outstanding of this kind goes first, so "send me
        # another" leaves one live link rather than a drawerful.
        self._tokens.discard_outstanding(user.id, purpose)

        # The only moment this value exists in readable form.
        token = generate_token()

        self._tokens.create(
            user_id=user.id,
            purpose=purpose,
            email=user.email.lower(),
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC) + lifetime,
        )
        self._session.commit()

        return token

    def _usable(
        self,
        token: str,
        purpose: UserTokenPurpose,
    ) -> tuple[UserToken, User]:
        """Resolve a link to the token and account it acts on.

        Five ways to fail and one answer to all of them, because the
        person holding this has proved nothing yet and every distinction
        would be a fact about somebody's account.
        """
        found = self._tokens.get_by_token_hash(hash_token(token))

        if found is None or found.purpose != purpose:
            # Wrong kind counts as unknown. A verification link is easy
            # to come by and lives for days; if it could be spent as a
            # password reset, that is what it would be worth.
            raise InvalidVerificationTokenError

        if not found.is_usable_at(datetime.now(UTC)):
            raise InvalidVerificationTokenError

        user = self._repository.get(found.user_id)

        if user is None or not user.is_active:
            raise InvalidVerificationTokenError

        if found.email != user.email.lower():
            # The account has moved to a different address since this was
            # sent. What the holder can prove is that they read mail at
            # the old one, and that is no longer a claim on this account.
            raise InvalidVerificationTokenError

        return found, user


def get_user_token_repository(session: SessionDep) -> UserTokenRepository:
    return UserTokenRepository(session)


UserTokenRepositoryDep = Annotated[
    UserTokenRepository,
    Depends(get_user_token_repository),
]


def get_verification_service(
    session: SessionDep,
    tokens: UserTokenRepositoryDep,
    users: UserServiceDep,
    repository: UserRepositoryDep,
    sessions: SessionServiceDep,
) -> VerificationService:
    return VerificationService(
        session=session,
        tokens=tokens,
        users=users,
        repository=repository,
        sessions=sessions,
    )


VerificationServiceDep = Annotated[
    VerificationService,
    Depends(get_verification_service),
]
