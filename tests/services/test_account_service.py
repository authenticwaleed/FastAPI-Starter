"""Phase 1 acceptance: a user may act on their own account and no other."""

from inspect import signature

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import (
    EmailAlreadyExistsError,
    IncorrectPasswordError,
    UserNotFoundError,
)
from app.core.security import verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.schemas.account import AccountUpdate, PasswordChange
from app.schemas.user import UserCreate
from app.services.account_service import AccountService
from app.services.user_service import UserService

PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "a different correct horse"


@pytest.fixture
def users(db_session: Session, user_repository: UserRepository) -> UserService:
    return UserService(session=db_session, repository=user_repository)


@pytest.fixture
def service(
    users: UserService,
    membership_repository: WorkspaceMembershipRepository,
) -> AccountService:
    return AccountService(users=users, memberships=membership_repository)


@pytest.fixture
def account(users: UserService) -> User:
    return users.create_user(
        UserCreate(name="Ada Lovelace", email="ada@example.com", password=PASSWORD)
    )


@pytest.fixture
def other(users: UserService) -> User:
    return users.create_user(
        UserCreate(name="Alan Turing", email="alan@example.com", password=PASSWORD)
    )


def test_update_changes_the_supplied_fields(
    service: AccountService,
    account: User,
) -> None:
    updated = service.update(account, AccountUpdate(name="Ada L"))

    assert updated.name == "Ada L"
    assert updated.email == "ada@example.com"


def test_update_can_change_the_email(
    service: AccountService,
    account: User,
) -> None:
    updated = service.update(account, AccountUpdate(email="ada.l@example.com"))

    assert updated.email == "ada.l@example.com"


def test_update_rejects_an_address_someone_else_holds(
    service: AccountService,
    account: User,
    other: User,
) -> None:
    with pytest.raises(EmailAlreadyExistsError):
        service.update(account, AccountUpdate(email=other.email))


def test_update_leaves_every_other_account_alone(
    service: AccountService,
    account: User,
    other: User,
) -> None:
    service.update(account, AccountUpdate(name="Ada L"))

    assert other.name == "Alan Turing"
    assert other.email == "alan@example.com"


def test_change_password_replaces_the_stored_hash(
    service: AccountService,
    account: User,
) -> None:
    service.change_password(
        account,
        PasswordChange(current_password=PASSWORD, new_password=NEW_PASSWORD),
    )

    assert verify_password(NEW_PASSWORD, account.hashed_password)
    assert not verify_password(PASSWORD, account.hashed_password)


def test_change_password_never_stores_the_plain_password(
    service: AccountService,
    account: User,
) -> None:
    service.change_password(
        account,
        PasswordChange(current_password=PASSWORD, new_password=NEW_PASSWORD),
    )

    assert account.hashed_password != NEW_PASSWORD


def test_change_password_requires_the_current_one(
    service: AccountService,
    account: User,
) -> None:
    with pytest.raises(IncorrectPasswordError):
        service.change_password(
            account,
            PasswordChange(current_password="not it", new_password=NEW_PASSWORD),
        )


def test_a_refused_password_change_leaves_the_old_one_working(
    service: AccountService,
    account: User,
) -> None:
    with pytest.raises(IncorrectPasswordError):
        service.change_password(
            account,
            PasswordChange(current_password="not it", new_password=NEW_PASSWORD),
        )

    assert verify_password(PASSWORD, account.hashed_password)


def test_delete_removes_the_account(
    service: AccountService,
    users: UserService,
    account: User,
) -> None:
    account_id = account.id

    service.delete(account)

    with pytest.raises(UserNotFoundError):
        users.get_user(account_id)


def test_delete_leaves_every_other_account_alone(
    service: AccountService,
    users: UserService,
    account: User,
    other: User,
) -> None:
    service.delete(account)

    assert users.get_user(other.id).email == "alan@example.com"


def test_no_method_takes_an_id_a_caller_could_substitute() -> None:
    # The authorization argument of this phase, as a test. Every method
    # works from the User the token resolved to, so there is no parameter
    # here that could name somebody else's account in the first place.
    for name in ("update", "change_password", "delete"):
        parameters = signature(getattr(AccountService, name)).parameters

        assert parameters["user"].annotation is User
        assert not [parameter for parameter in parameters if parameter.endswith("_id")]
