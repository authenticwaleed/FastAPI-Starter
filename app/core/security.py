import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings

# Argon2id, the algorithm pwdlib currently recommends. Verification reads the
# algorithm from the stored hash, so changing this later does not invalidate
# existing passwords.
_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Return a hash safe to store. The plain password is never persisted."""
    return _password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return _password_hash.verify(password, hashed_password)


@lru_cache
def unusable_hash() -> str:
    """A hash of a password nobody holds, for verifying against on purpose.

    Login uses it when the email is unknown, so a missing account costs the
    same time as a wrong password and the two cannot be told apart by
    timing them. Cached because Argon2 is deliberately slow and this value
    never changes.
    """
    return hash_password("no password hashes to this value")


def create_access_token(subject: str, *, expires_in: timedelta | None = None) -> str:
    """Sign a bearer token identifying `subject`.

    `expires_in` overrides the configured lifetime. It exists so tests can
    mint an already-expired token instead of waiting for one to age.
    """
    settings = get_settings()

    issued_at = datetime.now(UTC)
    lifetime = (
        expires_in
        if expires_in is not None
        else timedelta(minutes=settings.access_token_expire_minutes)
    )

    return jwt.encode(
        {
            "sub": subject,
            "iat": issued_at,
            "exp": issued_at + lifetime,
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> str:
    """Return the subject of a valid token.

    Raises `jwt.InvalidTokenError` if the signature, the expiry or the
    payload does not hold up. `ExpiredSignatureError` is a subclass of it,
    so an expired token and a forged one fail the same way.
    """
    settings = get_settings()

    payload = jwt.decode(
        token,
        settings.jwt_secret_key.get_secret_value(),
        # Pinning the algorithm is the point of this argument: without it a
        # token could arrive claiming `alg: none` and be accepted unsigned.
        # Never read the algorithm out of the token being verified.
        algorithms=[settings.jwt_algorithm],
    )

    subject = payload.get("sub")

    if not isinstance(subject, str):
        raise jwt.InvalidTokenError("token carries no subject")

    return subject


def generate_token() -> str:
    """A single-use secret to put in a link, such as an invitation.

    32 bytes from the system CSPRNG, URL-safe so it survives being pasted
    into an address bar. This is the only moment the value exists in
    readable form: what gets stored is the hash below.
    """
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash a link token for storage, so a leaked table is not a set of keys.

    SHA-256, deliberately, where a password gets Argon2. The two are
    protecting against different things. A password is low-entropy and
    guessable, so its hash must be slow and salted -- and being salted is
    exactly why you cannot look a password up by its hash. This value is
    256 bits of uniform randomness with no dictionary to attack, so speed
    buys an attacker nothing, and an unsalted digest is what lets the
    lookup be a single indexed query rather than a slow verification
    against every outstanding invitation in the table.
    """
    return hashlib.sha256(token.encode()).hexdigest()
