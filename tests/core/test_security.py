"""Password hashing and access tokens.

Hashing was pulled forward from Phase 7 because the NOT NULL
hashed_password column makes user creation impossible without it. The token
half arrives with Phase 8, where login finally has a use for verification.

Phase 15 added the session claim. A token now says which sign-in it came
from as well as who it belongs to, and one without that is not a token
this application issues.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_token,
    hash_password,
    hash_token,
    unusable_hash,
    verify_password,
)

PASSWORD = "correct horse battery staple"

SESSION_ID = uuid.UUID("2f1a4c60-0d5f-4a3f-9a5b-4a0c3e7d1b22")


def _token(subject: str = "42", **kwargs: Any) -> str:
    return create_access_token(subject, session_id=SESSION_ID, **kwargs)


def _future() -> datetime:
    return datetime.now(UTC) + timedelta(minutes=5)


def _sign(payload: dict[str, Any]) -> str:
    """Sign a payload of our choosing, to test what decoding refuses."""
    settings = get_settings()

    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


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
    assert decode_access_token(_token()).subject == "42"


def test_a_fresh_token_names_the_session_it_came_from() -> None:
    assert decode_access_token(_token()).session_id == SESSION_ID


def test_the_token_expires_after_the_configured_lifetime() -> None:
    payload = _read_payload(_token())

    lifetime = payload["exp"] - payload["iat"]

    assert lifetime == get_settings().access_token_expire_minutes * 60


def test_the_token_carries_nothing_but_its_claims() -> None:
    # A JWT payload is signed, not encrypted: anyone holding the token can
    # read it. Both claims here are identifiers; nothing personal belongs
    # in there.
    assert set(_read_payload(_token())) == {"sub", "sid", "iat", "exp"}


def test_an_expired_token_is_rejected() -> None:
    expired = _token(expires_in=timedelta(seconds=-1))

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired)


def test_an_expired_token_fails_as_an_invalid_token() -> None:
    # ExpiredSignatureError subclasses InvalidTokenError, so callers can
    # treat "expired" and "forged" identically with one except clause.
    expired = _token(expires_in=timedelta(seconds=-1))

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(expired)


def test_a_tampered_token_is_rejected() -> None:
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(_tamper(_token()))


def test_a_token_signed_with_another_key_is_rejected() -> None:
    forged = jwt.encode(
        {"sub": "42", "sid": str(SESSION_ID), "exp": _future()},
        "not the application signing key, and long enough not to warn",
        algorithm="HS256",
    )

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(forged)


def test_an_unsigned_token_is_rejected() -> None:
    # The classic JWT attack: strip the signature and claim `alg: none`.
    # Pinning algorithms at decode time is what stops it.
    unsigned = jwt.encode(
        {"sub": "42", "sid": str(SESSION_ID), "exp": _future()},
        None,
        algorithm="none",
    )

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(unsigned)


def test_a_token_without_a_subject_is_rejected() -> None:
    subjectless = _sign({"sid": str(SESSION_ID), "exp": _future()})

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(subjectless)


def test_a_token_without_a_session_is_rejected() -> None:
    # What this application signed before sessions existed, and what an
    # attacker would mint if they ever got the key and did not know the
    # shape. A token with no session behind it cannot be revoked, which is
    # the reason the claim is there at all.
    sessionless = _sign({"sub": "42", "exp": _future()})

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(sessionless)


def test_a_token_whose_session_is_not_an_id_is_rejected() -> None:
    nonsense = _sign({"sub": "42", "sid": "not-a-uuid", "exp": _future()})

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(nonsense)


def test_garbage_is_rejected() -> None:
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token("not-a-token")


def test_a_generated_token_is_url_safe() -> None:
    token = generate_token()

    assert token == quote(token, safe="")


def test_two_generated_tokens_differ() -> None:
    # Not a randomness test, which a unit test cannot do. It catches the
    # mistake that matters: a constant where a secret should be.
    assert generate_token() != generate_token()


def test_a_generated_token_carries_enough_entropy_to_be_unguessable() -> None:
    # 32 bytes, URL-safe base64: 43 characters once the padding is gone.
    assert len(generate_token()) >= 43


def test_hashing_a_token_is_repeatable() -> None:
    # Unlike a password hash, and deliberately: this is what lets an
    # invitation be found by one indexed lookup rather than by verifying
    # every outstanding row.
    token = generate_token()

    assert hash_token(token) == hash_token(token)


def test_different_tokens_hash_differently() -> None:
    assert hash_token(generate_token()) != hash_token(generate_token())


def test_a_token_hash_does_not_contain_the_token() -> None:
    token = generate_token()

    assert token not in hash_token(token)
