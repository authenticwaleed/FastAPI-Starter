"""Phase 5 acceptance: the service holds business rules, not queries."""

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import EmailAlreadyExistsError, UserNotFoundError
from app.core.security import verify_password
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserUpdate
from app.services.user_service import UserService

PASSWORD = "correct horse battery staple"


@pytest.fixture
def service(db_session: Session, user_repository: UserRepository) -> UserService:
    return UserService(session=db_session, repository=user_repository)


def _payload(email: str = "ada@example.com") -> UserCreate:
    return UserCreate(name="Ada Lovelace", email=email, password=PASSWORD)


def _total(service: UserService) -> int:
    _, total = service.list_users()
    return total


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

    assert _total(service) == 1


def test_users_with_different_emails_are_both_stored(
    service: UserService,
) -> None:
    service.create_user(_payload("ada@example.com"))
    service.create_user(_payload("alan@example.com"))

    assert _total(service) == 2


def test_get_user_raises_when_missing(service: UserService) -> None:
    with pytest.raises(UserNotFoundError):
        service.get_user(999)


def test_not_found_error_carries_the_id(service: UserService) -> None:
    with pytest.raises(UserNotFoundError) as excinfo:
        service.get_user(999)

    assert excinfo.value.user_id == 999


def test_get_user_returns_the_created_user(service: UserService) -> None:
    created = service.create_user(_payload())

    found = service.get_user(created.id)

    assert found is not None
    assert found.email == "ada@example.com"


def test_list_users_returns_the_first_page_by_default(
    service: UserService,
) -> None:
    for index in range(3):
        service.create_user(_payload(f"user{index}@example.com"))

    users, total = service.list_users()

    assert len(users) == 3
    assert total == 3


def test_list_users_slices_by_page(service: UserService) -> None:
    for index in range(3):
        service.create_user(_payload(f"user{index}@example.com"))

    first, _ = service.list_users(page=1, page_size=2)
    second, _ = service.list_users(page=2, page_size=2)

    assert [user.email for user in first] == [
        "user0@example.com",
        "user1@example.com",
    ]
    assert [user.email for user in second] == ["user2@example.com"]


def test_total_counts_every_user_not_just_the_page(service: UserService) -> None:
    for index in range(3):
        service.create_user(_payload(f"user{index}@example.com"))

    users, total = service.list_users(page=1, page_size=1)

    assert len(users) == 1
    assert total == 3


def test_update_user_changes_the_supplied_fields(service: UserService) -> None:
    created = service.create_user(_payload())

    updated = service.update_user(created.id, UserUpdate(name="Ada L"))

    assert updated.name == "Ada L"
    assert updated.email == "ada@example.com"


def test_update_user_rehashes_a_new_password(service: UserService) -> None:
    created = service.create_user(_payload())

    updated = service.update_user(created.id, UserUpdate(password="a new password"))

    assert updated.hashed_password != "a new password"
    assert verify_password("a new password", updated.hashed_password)
    assert not verify_password(PASSWORD, updated.hashed_password)


def test_update_user_rejects_an_email_another_user_owns(
    service: UserService,
) -> None:
    service.create_user(_payload("ada@example.com"))
    alan = service.create_user(_payload("alan@example.com"))

    with pytest.raises(EmailAlreadyExistsError):
        service.update_user(alan.id, UserUpdate(email="ada@example.com"))


def test_update_user_accepts_the_address_it_already_has(
    service: UserService,
) -> None:
    created = service.create_user(_payload())

    updated = service.update_user(
        created.id,
        UserUpdate(email="ada@example.com", name="Ada L"),
    )

    assert updated.name == "Ada L"


def test_update_user_raises_when_missing(service: UserService) -> None:
    with pytest.raises(UserNotFoundError):
        service.update_user(999, UserUpdate(name="Nobody"))


def test_delete_user_removes_the_user(service: UserService) -> None:
    created = service.create_user(_payload())

    service.delete_user(created.id)

    assert _total(service) == 0
    with pytest.raises(UserNotFoundError):
        service.get_user(created.id)


def test_delete_user_raises_when_missing(service: UserService) -> None:
    with pytest.raises(UserNotFoundError):
        service.delete_user(999)
