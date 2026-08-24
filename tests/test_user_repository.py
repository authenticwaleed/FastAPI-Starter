"""Phase 5 acceptance: the repository owns persistence and tests in isolation.

No FastAPI app and no service layer here — just the repository and a session.
"""

from app.repositories.user_repository import UserRepository

HASH = "$argon2id$v=19$not-a-real-hash"


def _create(repository: UserRepository, email: str, name: str = "Ada") -> None:
    repository.create(name=name, email=email, hashed_password=HASH)


def test_create_assigns_a_primary_key_without_committing(
    user_repository: UserRepository,
) -> None:
    user = user_repository.create(
        name="Ada Lovelace",
        email="ada@example.com",
        hashed_password=HASH,
    )

    # flush() populates the id from the sequence; commit stays with the caller.
    assert user.id is not None


def test_create_populates_server_side_defaults(
    user_repository: UserRepository,
) -> None:
    user = user_repository.create(
        name="Ada Lovelace",
        email="ada@example.com",
        hashed_password=HASH,
    )

    assert user.is_active is True
    assert user.created_at is not None
    assert user.updated_at is not None


def test_get_returns_the_stored_user(user_repository: UserRepository) -> None:
    created = user_repository.create(
        name="Ada Lovelace",
        email="ada@example.com",
        hashed_password=HASH,
    )

    assert user_repository.get(created.id) is created


def test_get_returns_none_for_an_unknown_id(
    user_repository: UserRepository,
) -> None:
    assert user_repository.get(999) is None


def test_get_by_email_finds_the_user(user_repository: UserRepository) -> None:
    _create(user_repository, "ada@example.com")

    found = user_repository.get_by_email("ada@example.com")

    assert found is not None
    assert found.email == "ada@example.com"


def test_get_by_email_returns_none_when_absent(
    user_repository: UserRepository,
) -> None:
    assert user_repository.get_by_email("nobody@example.com") is None


def test_list_is_empty_before_anything_is_created(
    user_repository: UserRepository,
) -> None:
    assert user_repository.list() == []


def test_list_returns_users_ordered_by_id(
    user_repository: UserRepository,
) -> None:
    _create(user_repository, "ada@example.com", name="Ada")
    _create(user_repository, "alan@example.com", name="Alan")

    assert [user.email for user in user_repository.list()] == [
        "ada@example.com",
        "alan@example.com",
    ]
