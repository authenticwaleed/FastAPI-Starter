"""Phase 7 acceptance: provider tokens are not stored in plain text."""

import pytest

from app.core.encryption import decrypt, encrypt, generate_key

TOKEN = "EAAG...a-provider-access-token"


def test_a_token_survives_a_round_trip() -> None:
    assert decrypt(encrypt(TOKEN)) == TOKEN


def test_the_ciphertext_does_not_contain_the_token() -> None:
    assert TOKEN not in encrypt(TOKEN)


def test_encrypting_twice_gives_two_different_values() -> None:
    # Fernet carries its own IV, so the same input never encrypts the
    # same way -- which is also why this column can never be searched.
    # Nothing needs to search it.
    assert encrypt(TOKEN) != encrypt(TOKEN)


def test_both_still_decrypt_to_the_same_secret() -> None:
    assert decrypt(encrypt(TOKEN)) == decrypt(encrypt(TOKEN)) == TOKEN


def test_a_tampered_value_will_not_decrypt() -> None:
    # Fernet authenticates the ciphertext, so an edited column fails
    # rather than decrypting into something else.
    ciphertext = encrypt(TOKEN)
    swapped = "B" if ciphertext[20] != "B" else "C"
    tampered = ciphertext[:20] + swapped + ciphertext[21:]

    with pytest.raises(Exception, match="could not be decrypted"):
        decrypt(tampered)


def test_a_value_from_another_key_will_not_decrypt() -> None:
    from cryptography.fernet import Fernet

    stranger = Fernet(generate_key().encode()).encrypt(TOKEN.encode()).decode()

    with pytest.raises(Exception, match="could not be decrypted"):
        decrypt(stranger)


def test_a_generated_key_is_usable() -> None:
    from cryptography.fernet import Fernet

    cipher = Fernet(generate_key().encode())

    assert cipher.decrypt(cipher.encrypt(TOKEN.encode())).decode() == TOKEN


def test_two_generated_keys_differ() -> None:
    assert generate_key() != generate_key()
