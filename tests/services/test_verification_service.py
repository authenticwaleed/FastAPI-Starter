"""Phase 16 acceptance: the token mechanics, without going through HTTP.

What a single-use link is worth comes down to four questions -- can it be
spent twice, can it be spent late, can it be spent as something it is not,
and can it still be spent after the address it was sent to stopped being
the account's. All four are answered here.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidVerificationTokenError
from app.core.security import hash_token, verify_password
from app.models.user import User
from app.models.user_token import UserToken, UserTokenPurpose
from app.repositories.user_repository import UserRepository
from app.repositories.user_session_repository import UserSessionRepository
from app.repositories.user_token_repository import UserTokenRepository
from app.schemas.user import UserCreate, UserUpdate
from app.services.session_service import SessionService
from app.services.user_service import UserService
from app.services.verification_service import VerificationService

EMAIL = "ada@example.com"
PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "a different correct horse"


@pytest.fixture
def users(db_session: Session, user_repository: UserRepository) -> UserService:
    return UserService(session=db_session, repository=user_repository)


@pytest.fixture
def sessions(
    db_session: Session,
    user_session_repository: UserSessionRepository,
) -> SessionService:
    return SessionService(session=db_session, repository=user_session_repository)


@pytest.fixture
def service(
    db_session: Session,
    user_token_repository: UserTokenRepository,
    users: UserService,
    user_repository: UserRepository,
    sessions: SessionService,
) -> VerificationService:
    return VerificationService(
        session=db_session,
        tokens=user_token_repository,
        users=users,
        repository=user_repository,
        sessions=sessions,
    )


@pytest.fixture
def account(users: UserService) -> User:
    return users.create_user(
        UserCreate(name="Ada Lovelace", email=EMAIL, password=PASSWORD)
    )


def _token_in(body: str) -> str:
    return next(part for part in body.split() if len(part) >= 43)


def _rows(session: Session, purpose: UserTokenPurpose) -> list[UserToken]:
    return list(
        session.scalars(select(UserToken).where(UserToken.purpose == purpose)).all()
    )


def _age(session: Session, token: UserToken) -> None:
    token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.flush()


# --- issuing --------------------------------------------------------------


def test_a_message_is_built_for_an_unconfirmed_account(
    service: VerificationService,
    account: User,
) -> None:
    message = service.verification_email_for(EMAIL)

    assert message is not None
    assert message.to == EMAIL


def test_nothing_is_built_for_an_address_nobody_registered(
    service: VerificationService,
) -> None:
    assert service.verification_email_for("nobody@example.com") is None
    assert service.reset_email_for("nobody@example.com") is None


def test_nothing_is_built_for_a_deactivated_account(
    service: VerificationService,
    db_session: Session,
    account: User,
) -> None:
    account.is_active = False
    db_session.flush()

    assert service.verification_email_for(EMAIL) is None
    assert service.reset_email_for(EMAIL) is None


def test_nothing_is_built_for_an_address_already_confirmed(
    service: VerificationService,
    account: User,
) -> None:
    message = service.verification_email_for(EMAIL)
    assert message is not None
    service.verify_email(_token_in(message.body))

    assert service.verification_email_for(EMAIL) is None


def test_an_unconfirmed_account_can_still_reset_its_password(
    service: VerificationService,
    account: User,
) -> None:
    # Refusing would leave the account with no way back in at all.
    assert account.email_verified_at is None
    assert service.reset_email_for(EMAIL) is not None


def test_the_token_itself_is_never_stored(
    service: VerificationService,
    db_session: Session,
    account: User,
) -> None:
    message = service.verification_email_for(EMAIL)
    assert message is not None
    token = _token_in(message.body)

    rows = _rows(db_session, UserTokenPurpose.EMAIL_VERIFICATION)

    assert len(rows) == 1
    assert rows[0].token_hash == hash_token(token)
    assert token not in rows[0].token_hash


def test_asking_again_leaves_one_live_link(
    service: VerificationService,
    db_session: Session,
    account: User,
) -> None:
    service.verification_email_for(EMAIL)
    service.verification_email_for(EMAIL)

    assert len(_rows(db_session, UserTokenPurpose.EMAIL_VERIFICATION)) == 1


def test_asking_for_one_kind_leaves_the_other_alone(
    service: VerificationService,
    db_session: Session,
    account: User,
) -> None:
    confirmation = service.verification_email_for(EMAIL)
    assert confirmation is not None

    service.reset_email_for(EMAIL)

    # The confirmation link still works after a reset was requested.
    service.verify_email(_token_in(confirmation.body))
    assert account.email_verified_at is not None


def test_a_reset_link_is_shorter_lived_than_a_confirmation(
    service: VerificationService,
    db_session: Session,
    account: User,
) -> None:
    service.verification_email_for(EMAIL)
    service.reset_email_for(EMAIL)

    confirmation = _rows(db_session, UserTokenPurpose.EMAIL_VERIFICATION)[0]
    reset = _rows(db_session, UserTokenPurpose.PASSWORD_RESET)[0]

    assert reset.expires_at < confirmation.expires_at


# --- spending -------------------------------------------------------------


def test_confirming_records_when(
    service: VerificationService,
    account: User,
) -> None:
    message = service.verification_email_for(EMAIL)
    assert message is not None

    user = service.verify_email(_token_in(message.body))

    assert user.email_verified_at is not None


def test_confirming_spends_the_link(
    service: VerificationService,
    db_session: Session,
    account: User,
) -> None:
    message = service.verification_email_for(EMAIL)
    assert message is not None

    service.verify_email(_token_in(message.body))

    assert _rows(db_session, UserTokenPurpose.EMAIL_VERIFICATION)[0].used_at is not None


def test_a_spent_link_is_refused(
    service: VerificationService,
    account: User,
) -> None:
    message = service.verification_email_for(EMAIL)
    assert message is not None
    token = _token_in(message.body)
    service.verify_email(token)

    with pytest.raises(InvalidVerificationTokenError):
        service.verify_email(token)


def test_an_expired_link_is_refused(
    service: VerificationService,
    db_session: Session,
    account: User,
) -> None:
    message = service.verification_email_for(EMAIL)
    assert message is not None
    _age(db_session, _rows(db_session, UserTokenPurpose.EMAIL_VERIFICATION)[0])

    with pytest.raises(InvalidVerificationTokenError):
        service.verify_email(_token_in(message.body))


def test_a_link_nobody_was_sent_is_refused(
    service: VerificationService,
    account: User,
) -> None:
    with pytest.raises(InvalidVerificationTokenError):
        service.verify_email("not a link anybody was sent")


def test_a_confirmation_link_cannot_reset_a_password(
    service: VerificationService,
    account: User,
) -> None:
    message = service.verification_email_for(EMAIL)
    assert message is not None

    with pytest.raises(InvalidVerificationTokenError):
        service.reset_password(_token_in(message.body), NEW_PASSWORD)


def test_a_reset_link_cannot_confirm_an_address(
    service: VerificationService,
    account: User,
) -> None:
    message = service.reset_email_for(EMAIL)
    assert message is not None

    with pytest.raises(InvalidVerificationTokenError):
        service.verify_email(_token_in(message.body))


def test_a_link_is_refused_once_the_address_has_changed(
    service: VerificationService,
    users: UserService,
    account: User,
) -> None:
    # What the holder can prove is that they read mail at the old
    # address, and that is no longer a claim on this account.
    message = service.reset_email_for(EMAIL)
    assert message is not None

    users.update_user(account.id, UserUpdate(email="ada.lovelace@example.com"))

    with pytest.raises(InvalidVerificationTokenError):
        service.reset_password(_token_in(message.body), NEW_PASSWORD)


def test_a_link_is_refused_once_the_account_is_deactivated(
    service: VerificationService,
    db_session: Session,
    account: User,
) -> None:
    message = service.reset_email_for(EMAIL)
    assert message is not None

    account.is_active = False
    db_session.flush()

    with pytest.raises(InvalidVerificationTokenError):
        service.reset_password(_token_in(message.body), NEW_PASSWORD)


# --- resetting ------------------------------------------------------------


def test_resetting_replaces_the_stored_hash(
    service: VerificationService,
    account: User,
) -> None:
    message = service.reset_email_for(EMAIL)
    assert message is not None

    user = service.reset_password(_token_in(message.body), NEW_PASSWORD)

    assert verify_password(NEW_PASSWORD, user.hashed_password)
    assert not verify_password(PASSWORD, user.hashed_password)


def test_resetting_never_stores_the_plain_password(
    service: VerificationService,
    account: User,
) -> None:
    message = service.reset_email_for(EMAIL)
    assert message is not None

    user = service.reset_password(_token_in(message.body), NEW_PASSWORD)

    assert NEW_PASSWORD not in user.hashed_password


def test_resetting_ends_every_session(
    service: VerificationService,
    sessions: SessionService,
    account: User,
) -> None:
    laptop = sessions.begin(account)
    phone = sessions.begin(account)
    message = service.reset_email_for(EMAIL)
    assert message is not None

    service.reset_password(_token_in(message.body), NEW_PASSWORD)

    assert sessions.resolve(laptop.session.id) is None
    assert sessions.resolve(phone.session.id) is None


def test_resetting_confirms_the_address(
    service: VerificationService,
    account: User,
) -> None:
    message = service.reset_email_for(EMAIL)
    assert message is not None

    user = service.reset_password(_token_in(message.body), NEW_PASSWORD)

    assert user.email_verified_at is not None


def test_resetting_leaves_an_earlier_confirmation_time_alone(
    service: VerificationService,
    account: User,
) -> None:
    # Confirmed once is confirmed. Moving the timestamp forward would
    # rewrite when it actually happened.
    confirmation = service.verification_email_for(EMAIL)
    assert confirmation is not None
    service.verify_email(_token_in(confirmation.body))
    confirmed_at = account.email_verified_at

    reset = service.reset_email_for(EMAIL)
    assert reset is not None
    service.reset_password(_token_in(reset.body), NEW_PASSWORD)

    assert account.email_verified_at == confirmed_at


def test_resetting_spends_the_link(
    service: VerificationService,
    db_session: Session,
    account: User,
) -> None:
    message = service.reset_email_for(EMAIL)
    assert message is not None

    service.reset_password(_token_in(message.body), NEW_PASSWORD)

    assert _rows(db_session, UserTokenPurpose.PASSWORD_RESET)[0].used_at is not None
