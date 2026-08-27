"""Phase 8 acceptance: credentials and tokens, without going through HTTP.

Phase 15 put a session behind every token. Login opens one, and resolving
a token now means resolving the session it names -- so the tests that used
to mint a token by hand have to say which sign-in it belongs to.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import (
    EmailAlreadyExistsError,
    InactiveUserError,
    InvalidCredentialsError,
)
from app.core.security import create_access_token, decode_access_token
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.repositories.user_session_repository import UserSessionRepository
from app.schemas.auth import LoginRequest
from app.schemas.user import UserCreate
from app.services.auth_service import AuthService
from app.services.session_service import SessionService
from app.services.user_service import UserService

EMAIL = "ada@example.com"
PASSWORD = "correct horse battery staple"


@pytest.fixture
def auth_service(
    db_session: Session,
    user_repository: UserRepository,
    user_session_repository: UserSessionRepository,
) -> AuthService:
    users = UserService(session=db_session, repository=user_repository)
    sessions = SessionService(
        session=db_session,
        repository=user_session_repository,
    )

    return AuthService(
        users=users,
        repository=user_repository,
        sessions=sessions,
    )


def _registration(email: str = EMAIL) -> UserCreate:
    return UserCreate(name="Ada Lovelace", email=email, password=PASSWORD)


def _register(service: AuthService, email: str = EMAIL) -> User:
    return service.register(_registration(email))


def _deactivate(session: Session, user: User) -> None:
    user.is_active = False
    session.flush()


def test_register_stores_the_password_as_a_hash(auth_service: AuthService) -> None:
    user = _register(auth_service)

    assert user.hashed_password != PASSWORD
    assert user.id is not None


def test_register_rejects_an_address_already_taken(
    auth_service: AuthService,
) -> None:
    _register(auth_service)

    with pytest.raises(EmailAlreadyExistsError):
        _register(auth_service)


def test_a_registered_user_can_authenticate(auth_service: AuthService) -> None:
    registered = _register(auth_service)

    assert auth_service.authenticate(EMAIL, PASSWORD) is registered


def test_authenticate_rejects_a_wrong_password(auth_service: AuthService) -> None:
    _register(auth_service)

    with pytest.raises(InvalidCredentialsError):
        auth_service.authenticate(EMAIL, "not the password")


def test_authenticate_rejects_an_unknown_address(
    auth_service: AuthService,
) -> None:
    with pytest.raises(InvalidCredentialsError):
        auth_service.authenticate("nobody@example.com", PASSWORD)


def test_authenticate_rejects_a_deactivated_account(
    auth_service: AuthService,
    db_session: Session,
) -> None:
    user = _register(auth_service)
    _deactivate(db_session, user)

    with pytest.raises(InactiveUserError):
        auth_service.authenticate(EMAIL, PASSWORD)


def test_login_returns_a_bearer_token(auth_service: AuthService) -> None:
    _register(auth_service)

    token = auth_service.login(LoginRequest(email=EMAIL, password=PASSWORD))

    assert token.token_type == "bearer"
    assert token.access_token


def test_login_returns_a_refresh_token_as_well(auth_service: AuthService) -> None:
    _register(auth_service)

    token = auth_service.login(LoginRequest(email=EMAIL, password=PASSWORD))

    assert token.refresh_token
    assert token.refresh_token != token.access_token
    assert token.expires_in > 0


def test_the_token_identifies_the_user_by_id(auth_service: AuthService) -> None:
    registered = _register(auth_service)

    token = auth_service.login(LoginRequest(email=EMAIL, password=PASSWORD))

    assert decode_access_token(token.access_token).subject == str(registered.id)


def test_the_token_does_not_carry_the_address(auth_service: AuthService) -> None:
    _register(auth_service)

    token = auth_service.login(LoginRequest(email=EMAIL, password=PASSWORD))

    assert EMAIL not in token.access_token


def test_login_rejects_a_wrong_password(auth_service: AuthService) -> None:
    _register(auth_service)

    with pytest.raises(InvalidCredentialsError):
        auth_service.login(LoginRequest(email=EMAIL, password="not the password"))


def test_a_token_resolves_to_the_user_and_the_session(
    auth_service: AuthService,
) -> None:
    registered = _register(auth_service)

    token = auth_service.login(LoginRequest(email=EMAIL, password=PASSWORD))
    authenticated = auth_service.authenticate_token(token.access_token)

    assert authenticated.user is registered
    assert authenticated.session.user_id == registered.id
    assert decode_access_token(token.access_token).session_id == (
        authenticated.session.id
    )


def test_two_logins_are_two_sessions(auth_service: AuthService) -> None:
    # Which is what makes signing one device out mean anything.
    _register(auth_service)

    first = auth_service.login(LoginRequest(email=EMAIL, password=PASSWORD))
    second = auth_service.login(LoginRequest(email=EMAIL, password=PASSWORD))

    assert auth_service.authenticate_token(first.access_token).session.id != (
        auth_service.authenticate_token(second.access_token).session.id
    )


def test_a_token_is_rejected_once_its_session_has_gone(
    auth_service: AuthService,
) -> None:
    # The point of naming the session in the token: revocation lands on
    # the next request rather than whenever the token happened to expire.
    _register(auth_service)
    token = auth_service.login(LoginRequest(email=EMAIL, password=PASSWORD))

    auth_service.logout(token.refresh_token)

    with pytest.raises(InvalidCredentialsError):
        auth_service.authenticate_token(token.access_token)


def test_an_expired_token_is_rejected(auth_service: AuthService) -> None:
    registered = _register(auth_service)
    token = auth_service.login(LoginRequest(email=EMAIL, password=PASSWORD))
    session_id = auth_service.authenticate_token(token.access_token).session.id

    expired = create_access_token(
        str(registered.id),
        session_id=session_id,
        expires_in=timedelta(seconds=-1),
    )

    with pytest.raises(InvalidCredentialsError):
        auth_service.authenticate_token(expired)


def test_a_token_that_is_not_one_is_rejected(auth_service: AuthService) -> None:
    with pytest.raises(InvalidCredentialsError):
        auth_service.authenticate_token("not-a-token")


def test_a_subject_that_is_not_an_id_is_rejected(auth_service: AuthService) -> None:
    # Correctly signed by us, but the subject is not something `get()` can
    # look up. It must fail as a bad credential, not as a ValueError.
    with pytest.raises(InvalidCredentialsError):
        auth_service.authenticate_token(
            create_access_token("not-an-id", session_id=uuid.uuid4())
        )


def test_a_token_naming_a_session_that_does_not_exist_is_rejected(
    auth_service: AuthService,
) -> None:
    registered = _register(auth_service)

    with pytest.raises(InvalidCredentialsError):
        auth_service.authenticate_token(
            create_access_token(str(registered.id), session_id=uuid.uuid4())
        )


def test_a_token_whose_two_claims_disagree_is_rejected(
    auth_service: AuthService,
) -> None:
    # A real session, and a subject that is not the account it belongs to.
    # Nothing this application signs looks like that.
    _register(auth_service)
    other = _register(auth_service, "alan@example.com")
    token = auth_service.login(LoginRequest(email=EMAIL, password=PASSWORD))
    session_id = auth_service.authenticate_token(token.access_token).session.id

    with pytest.raises(InvalidCredentialsError):
        auth_service.authenticate_token(
            create_access_token(str(other.id), session_id=session_id)
        )


def test_a_token_for_a_deleted_account_is_rejected(
    auth_service: AuthService,
    user_repository: UserRepository,
) -> None:
    registered = _register(auth_service)
    token = auth_service.login(LoginRequest(email=EMAIL, password=PASSWORD))

    user_repository.delete(registered)

    with pytest.raises(InvalidCredentialsError):
        auth_service.authenticate_token(token.access_token)


def test_a_token_for_a_deactivated_account_is_rejected(
    auth_service: AuthService,
    db_session: Session,
) -> None:
    user = _register(auth_service)
    token = auth_service.login(LoginRequest(email=EMAIL, password=PASSWORD))

    _deactivate(db_session, user)

    with pytest.raises(InactiveUserError):
        auth_service.authenticate_token(token.access_token)


def test_refresh_returns_a_new_pair(auth_service: AuthService) -> None:
    _register(auth_service)
    first = auth_service.login(LoginRequest(email=EMAIL, password=PASSWORD))

    second = auth_service.refresh(first.refresh_token)

    assert second.refresh_token != first.refresh_token
    assert auth_service.authenticate_token(second.access_token).session.id == (
        auth_service.authenticate_token(first.access_token).session.id
    )
