"""Phase 5 acceptance: the service holds business rules, not queries."""

import pytest
from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate
from app.services.user_service import EmailAlreadyExistsError, UserService

PASSWORD = "correct horse battery staple"


@pytest.fixture
def service(db_session: Session, user_repository: UserRepository) -> UserService:
    return UserService(session=db_session, repository=user_repository)


def _payload(email: str = "ada@example.com") -> UserCreate:
    return UserCreate(name="Ada Lovelace", email=email, password=PASSWORD)


def test_create_user_stores_a_hash_and_never_the_password(
    service: UserService,
) -> None:
    user = service.create_user(_payload())

    assert user.hashed_password != PASSWORD
    assert verify_password(PASSWORD, user.hashed_password)


def test_create_user_rejects_a_duplicate_email(service: UserService) -> None:
    service.create_user(_payload())

    with pytest.raises(EmailAlreadyExistsError):
        service.create_user(_payload())


def test_duplicate_email_error_carries_the_address(service: UserService) -> None:
    service.create_user(_payload("ada@example.com"))

    with pytest.raises(EmailAlreadyExistsError) as excinfo:
        service.create_user(_payload("ada@example.com"))

    assert excinfo.value.email == "ada@example.com"


def test_a_rejected_duplicate_leaves_the_first_user_intact(
    service: UserService,
) -> None:
    service.create_user(_payload())

    with pytest.raises(EmailAlreadyExistsError):
        service.create_user(_payload())

    assert len(service.list_users()) == 1


def test_users_with_different_emails_are_both_stored(
    service: UserService,
) -> None:
    service.create_user(_payload("ada@example.com"))
    service.create_user(_payload("alan@example.com"))

    assert len(service.list_users()) == 2


def test_get_user_returns_none_when_missing(service: UserService) -> None:
    assert service.get_user(999) is None


def test_get_user_returns_the_created_user(service: UserService) -> None:
    created = service.create_user(_payload())

    found = service.get_user(created.id)

    assert found is not None
    assert found.email == "ada@example.com"
