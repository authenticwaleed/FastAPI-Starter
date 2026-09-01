from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import get_settings
from app.core.exceptions import EncryptionUnavailableError


@lru_cache
def _cipher() -> MultiFernet:
    """The configured cipher, or a clear refusal.

    Built lazily and cached, so importing this module does not require a
    key and only the features that actually store a secret depend on one.

    A MultiFernet even when there is one key, which is what makes rotating
    the key something a deployment can actually do. Encryption always uses
    the first; decryption tries each in turn. So the procedure is:

        1. put the new key first and the old one second, and deploy
        2. every token still decrypts, and everything written from now on
           uses the new key
        3. re-encrypt what is stored, or wait for it to be rewritten
        4. drop the old key

    Without the second slot, step 1 is a deployment where every stored
    provider token stops decrypting at once -- which means in practice
    that the key is never rotated, and a key nobody can rotate is one that
    lives for the life of the product.
    """
    settings = get_settings()

    if settings.encryption_key is None:
        raise EncryptionUnavailableError

    supplied = [settings.encryption_key, settings.encryption_key_previous]

    try:
        return MultiFernet(
            [Fernet(key.get_secret_value().encode()) for key in supplied if key]
        )
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

    Always the current key, never a previous one: an old key exists to
    read what it wrote, not to keep writing.
    """
    return _cipher().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Recover a stored secret.

    Tries the current key and then any previous one, which is what lets a
    key be rotated without a deployment in which every stored token stops
    working at once.

    Raises EncryptionUnavailableError if the value authenticates against
    none of them: a wrong key, a truncated column, a row edited by hand.
    Failing is the right outcome for all three.
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
