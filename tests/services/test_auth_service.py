"""Phase 8 acceptance: credentials and tokens, without going through HTTP."""

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
from app.schemas.auth import LoginRequest
from app.schemas.user import UserCreate
from app.services.auth_service import AuthService
from app.services.user_service import UserService

EMAIL = "ada@example.com"
PASSWORD = "correct horse battery staple"


@pytest.fixture
def auth_service(db_session: Session, user_repository: UserRepository) -> AuthService:
    users = UserService(session=db_session, repository=user_repository)

    return AuthService(users=users, repository=user_repository)


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


def test_the_token_identifies_the_user_by_id(auth_service: AuthService) -> None:
    registered = _register(auth_service)

    token = auth_service.login(LoginRequest(email=EMAIL, password=PASSWORD))

    assert decode_access_token(token.access_token) == str(registered.id)


def test_the_token_does_not_carry_the_address(auth_service: AuthService) -> None:
    _register(auth_service)

    token = auth_service.login(LoginRequest(email=EMAIL, password=PASSWORD))

    assert EMAIL not in token.access_token


def test_login_rejects_a_wrong_password(auth_service: AuthService) -> None:
    _register(auth_service)

    with pytest.raises(InvalidCredentialsError):
        auth_service.login(LoginRequest(email=EMAIL, password="not the password"))


def test_current_user_resolves_a_fresh_token(auth_service: AuthService) -> None:
    registered = _register(auth_service)

    token = auth_service.login(LoginRequest(email=EMAIL, password=PASSWORD))

    assert auth_service.current_user(token.access_token) is registered


def test_current_user_rejects_an_expired_token(auth_service: AuthService) -> None:
    registered = _register(auth_service)

    expired = create_access_token(str(registered.id), expires_in=timedelta(seconds=-1))

    with pytest.raises(InvalidCredentialsError):
        auth_service.current_user(expired)


def test_current_user_rejects_a_token_that_is_not_one(
    auth_service: AuthService,
) -> None:
    with pytest.raises(InvalidCredentialsError):
        auth_service.current_user("not-a-token")


def test_current_user_rejects_a_subject_that_is_not_an_id(
    auth_service: AuthService,
) -> None:
    # Correctly signed by us, but the subject is not something `get()` can
    # look up. It must fail as a bad credential, not as a ValueError.
    with pytest.raises(InvalidCredentialsError):
        auth_service.current_user(create_access_token("not-an-id"))


def test_current_user_rejects_a_token_for_a_deleted_account(
    auth_service: AuthService,
    user_repository: UserRepository,
) -> None:
    registered = _register(auth_service)
    token = auth_service.login(LoginRequest(email=EMAIL, password=PASSWORD))

    user_repository.delete(registered)

    with pytest.raises(InvalidCredentialsError):
        auth_service.current_user(token.access_token)


def test_current_user_rejects_a_deactivated_account(
    auth_service: AuthService,
    db_session: Session,
) -> None:
    user = _register(auth_service)
    token = auth_service.login(LoginRequest(email=EMAIL, password=PASSWORD))

    _deactivate(db_session, user)

    with pytest.raises(InactiveUserError):
        auth_service.current_user(token.access_token)
