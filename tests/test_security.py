"""Password hashing, pulled forward from Phase 7 because the NOT NULL
hashed_password column makes user creation impossible without it.

Phase 7 extends this with the login flow and its verification tests.
"""

from app.core.security import hash_password, verify_password

PASSWORD = "correct horse battery staple"


def test_hash_does_not_contain_the_password() -> None:
    assert PASSWORD not in hash_password(PASSWORD)


def test_hashing_is_salted() -> None:
    # Identical passwords must not produce identical hashes, or the database
    # would reveal which users share one.
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


def test_correct_password_verifies() -> None:
    assert verify_password(PASSWORD, hash_password(PASSWORD)) is True


def test_wrong_password_does_not_verify() -> None:
    assert verify_password("not the password", hash_password(PASSWORD)) is False


def test_hash_fits_the_database_column() -> None:
    # hashed_password is VARCHAR(255).
    assert len(hash_password(PASSWORD)) <= 255
