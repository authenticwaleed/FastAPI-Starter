import hashlib
import secrets
import uuid
from dataclasses import dataclass
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


@dataclass(frozen=True)
class AccessTokenClaims:
    """What a valid access token says, once it has been checked.

    Two claims, both identifiers: who the holder is, and which sign-in
    they are holding. Nothing personal -- a JWT payload is signed, not
    encrypted, so anybody with the token can read it.
    """

    subject: str
    session_id: uuid.UUID


def access_token_lifetime() -> timedelta:
    """How long a freshly minted access token is good for.

    Short on purpose: it is the window in which a stolen access token is
    worth anything, and the refresh token is what makes a short one
    workable. Exposed as a function so `expires_in` in a token response
    and the `exp` claim cannot disagree.
    """
    return timedelta(minutes=get_settings().access_token_expire_minutes)


def create_access_token(
    subject: str,
    *,
    session_id: uuid.UUID,
    expires_in: timedelta | None = None,
) -> str:
    """Sign a bearer token identifying `subject` within one session.

    The session is named in the token rather than looked up from the
    user, which is what lets a request be traced back to the sign-in it
    came from -- and so what lets signing one device out take effect on
    the next request rather than whenever the token happened to expire.

    `expires_in` overrides the configured lifetime. It exists so tests can
    mint an already-expired token instead of waiting for one to age.
    """
    settings = get_settings()

    issued_at = datetime.now(UTC)
    lifetime = expires_in if expires_in is not None else access_token_lifetime()

    return jwt.encode(
        {
            "sub": subject,
            "sid": str(session_id),
            "iat": issued_at,
            "exp": issued_at + lifetime,
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> AccessTokenClaims:
    """Return the claims of a valid token.

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

    session_id = payload.get("sid")

    if not isinstance(session_id, str):
        # Correctly signed, but not by any version of this application
        # that issues tokens now. A token with no session behind it
        # cannot be revoked, which is the whole point of carrying one.
        raise jwt.InvalidTokenError("token carries no session")

    try:
        return AccessTokenClaims(subject=subject, session_id=uuid.UUID(session_id))
    except ValueError:
        raise jwt.InvalidTokenError("token carries no session") from None


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
