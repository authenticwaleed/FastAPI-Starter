"""Phase 5 acceptance: the repository owns persistence and tests in isolation.

No FastAPI app and no service layer here — just the repository and a session.
"""

from app.repositories.user_repository import UserRepository

HASH = "$argon2id$v=19$not-a-real-hash"

# A page wide enough that these tests never accidentally exercise the limit.
PAGE = {"limit": 100, "offset": 0}


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
    assert user_repository.list(**PAGE) == []


def test_list_returns_users_ordered_by_id(
    user_repository: UserRepository,
) -> None:
    _create(user_repository, "ada@example.com", name="Ada")
    _create(user_repository, "alan@example.com", name="Alan")

    assert [user.email for user in user_repository.list(**PAGE)] == [
        "ada@example.com",
        "alan@example.com",
    ]


def test_list_returns_at_most_limit_users(
    user_repository: UserRepository,
) -> None:
    for index in range(3):
        _create(user_repository, f"user{index}@example.com")

    assert len(user_repository.list(limit=2, offset=0)) == 2


def test_list_skips_the_first_offset_users(
    user_repository: UserRepository,
) -> None:
    for index in range(3):
        _create(user_repository, f"user{index}@example.com")

    page = user_repository.list(limit=2, offset=2)

    assert [user.email for user in page] == ["user2@example.com"]


def test_list_past_the_end_is_empty(user_repository: UserRepository) -> None:
    _create(user_repository, "ada@example.com")

    assert user_repository.list(limit=10, offset=10) == []


def test_count_is_zero_before_anything_is_created(
    user_repository: UserRepository,
) -> None:
    assert user_repository.count() == 0


def test_count_covers_every_user_not_just_one_page(
    user_repository: UserRepository,
) -> None:
    for index in range(3):
        _create(user_repository, f"user{index}@example.com")

    assert len(user_repository.list(limit=1, offset=0)) == 1
    assert user_repository.count() == 3


def test_update_changes_the_given_field(user_repository: UserRepository) -> None:
    user = user_repository.create(
        name="Ada",
        email="ada@example.com",
        hashed_password=HASH,
    )

    user_repository.update(user, name="Ada Lovelace")

    assert user.name == "Ada Lovelace"


def test_update_leaves_omitted_fields_alone(
    user_repository: UserRepository,
) -> None:
    user = user_repository.create(
        name="Ada",
        email="ada@example.com",
        hashed_password=HASH,
    )

    user_repository.update(user, name="Ada Lovelace")

    assert user.email == "ada@example.com"
    assert user.hashed_password == HASH


def test_update_can_change_the_email(user_repository: UserRepository) -> None:
    user = user_repository.create(
        name="Ada",
        email="ada@example.com",
        hashed_password=HASH,
    )

    user_repository.update(user, email="ada.lovelace@example.com")

    assert user_repository.get_by_email("ada.lovelace@example.com") is user
    assert user_repository.get_by_email("ada@example.com") is None


def test_update_with_nothing_supplied_changes_nothing(
    user_repository: UserRepository,
) -> None:
    user = user_repository.create(
        name="Ada",
        email="ada@example.com",
        hashed_password=HASH,
    )

    user_repository.update(user)

    assert (user.name, user.email, user.hashed_password) == (
        "Ada",
        "ada@example.com",
        HASH,
    )


def test_delete_removes_the_user(user_repository: UserRepository) -> None:
    user = user_repository.create(
        name="Ada",
        email="ada@example.com",
        hashed_password=HASH,
    )

    user_repository.delete(user)

    assert user_repository.count() == 0
    assert user_repository.get_by_email("ada@example.com") is None


def test_delete_leaves_other_users_alone(
    user_repository: UserRepository,
) -> None:
    user = user_repository.create(
        name="Ada",
        email="ada@example.com",
        hashed_password=HASH,
    )
    _create(user_repository, "alan@example.com", name="Alan")

    user_repository.delete(user)

    assert [other.email for other in user_repository.list(**PAGE)] == [
        "alan@example.com",
    ]
