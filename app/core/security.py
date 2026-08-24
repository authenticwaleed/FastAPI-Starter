from pwdlib import PasswordHash

# Argon2id, the algorithm pwdlib currently recommends. Verification reads the
# algorithm from the stored hash, so changing this later does not invalidate
# existing passwords.
_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Return a hash safe to store. The plain password is never persisted."""
    return _password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return _password_hash.verify(password, hashed_password)
