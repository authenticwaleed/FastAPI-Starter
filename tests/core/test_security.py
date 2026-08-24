"""Password hashing and access tokens.

Hashing was pulled forward from Phase 7 because the NOT NULL
hashed_password column makes user creation impossible without it. The token
half arrives with Phase 8, where login finally has a use for verification.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    unusable_hash,
    verify_password,
)

PASSWORD = "correct horse battery staple"


def _future() -> datetime:
    return datetime.now(UTC) + timedelta(minutes=5)


def _read_payload(token: str) -> dict[str, Any]:
    """Decode without going through the application's own checks."""
    settings = get_settings()

    return jwt.decode(
        token,
        settings.jwt_secret_key.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
    )


def _tamper(token: str) -> str:
    """Return a token whose signature is guaranteed to be wrong.

    Changing the *last* character would not do: 32 bytes need 43 base64url
    characters to carry 256 bits, so the final one holds four significant
    bits and two spare. Three of its sixty-three alternatives therefore
    decode to the same signature and leave the token valid, which is a test
    that passes roughly nineteen runs in twenty. The first character of the
    signature carries a full six bits, so changing it always bites.
    """
    header, payload, signature = token.split(".")
    swapped = "B" if signature[0] != "B" else "C"

    return f"{header}.{payload}.{swapped}{signature[1:]}"


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


def test_nothing_verifies_against_the_unusable_hash() -> None:
    # It stands in for a missing account during login, so it must never
    # accidentally match a password someone might actually have chosen.
    assert verify_password(PASSWORD, unusable_hash()) is False
    assert verify_password("", unusable_hash()) is False


def test_a_fresh_token_decodes_to_its_subject() -> None:
    assert decode_access_token(create_access_token("42")) == "42"


def test_the_token_expires_after_the_configured_lifetime() -> None:
    payload = _read_payload(create_access_token("42"))

    lifetime = payload["exp"] - payload["iat"]

    assert lifetime == get_settings().access_token_expire_minutes * 60


def test_the_token_carries_nothing_but_its_claims() -> None:
    # A JWT payload is signed, not encrypted: anyone holding the token can
    # read it. Nothing personal belongs in there.
    assert set(_read_payload(create_access_token("42"))) == {"sub", "iat", "exp"}


def test_an_expired_token_is_rejected() -> None:
    expired = create_access_token("42", expires_in=timedelta(seconds=-1))

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired)


def test_an_expired_token_fails_as_an_invalid_token() -> None:
    # ExpiredSignatureError subclasses InvalidTokenError, so callers can
    # treat "expired" and "forged" identically with one except clause.
    expired = create_access_token("42", expires_in=timedelta(seconds=-1))

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(expired)


def test_a_tampered_token_is_rejected() -> None:
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(_tamper(create_access_token("42")))


def test_a_token_signed_with_another_key_is_rejected() -> None:
    forged = jwt.encode(
        {"sub": "42", "exp": _future()},
        "not the application signing key, and long enough not to warn",
        algorithm="HS256",
    )

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(forged)


def test_an_unsigned_token_is_rejected() -> None:
    # The classic JWT attack: strip the signature and claim `alg: none`.
    # Pinning algorithms at decode time is what stops it.
    unsigned = jwt.encode({"sub": "42", "exp": _future()}, None, algorithm="none")

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(unsigned)


def test_a_token_without_a_subject_is_rejected() -> None:
    settings = get_settings()
    subjectless = jwt.encode(
        {"exp": _future()},
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(subjectless)


def test_garbage_is_rejected() -> None:
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token("not-a-token")
