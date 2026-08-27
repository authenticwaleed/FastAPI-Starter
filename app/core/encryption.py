from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from app.core.exceptions import EncryptionUnavailableError


@lru_cache
def _cipher() -> Fernet:
    """The configured cipher, or a clear refusal.

    Built lazily and cached, so importing this module does not require a
    key and only the features that actually store a secret depend on one.
    """
    key = get_settings().encryption_key

    if key is None:
        raise EncryptionUnavailableError

    try:
        return Fernet(key.get_secret_value().encode())
    except (ValueError, TypeError) as exc:
        # A malformed key is a configuration mistake, and the message must
        # not quote the value it was given.
        raise EncryptionUnavailableError(
            "ENCRYPTION_KEY is not a valid Fernet key"
        ) from exc


def encrypt(plaintext: str) -> str:
    """Encrypt a secret for storage.

    Fernet: AES-128-CBC with an HMAC over the ciphertext, so a stored
    value that somebody has edited fails to decrypt rather than decrypting
    into something else. The output carries its own IV and timestamp,
    which is why the same input encrypts differently every time -- and why
    this can never be used to look a value up. Nothing needs to.
    """
    return _cipher().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Recover a stored secret.

    Raises EncryptionUnavailableError if the value does not authenticate:
    a wrong key, a truncated column, a row edited by hand. Failing is the
    right outcome for all three.
    """
    try:
        return _cipher().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise EncryptionUnavailableError(
            "A stored secret could not be decrypted with the configured key"
        ) from exc


def generate_key() -> str:
    """A new Fernet key, for the documentation to point at."""
    return Fernet.generate_key().decode()
