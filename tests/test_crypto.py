import os

from kairos.auth.crypto import decrypt, encrypt, generate_dek, unwrap_dek, wrap_dek


def test_dek_roundtrip():
    kek = os.urandom(32)
    dek = generate_dek()
    wrapped = wrap_dek(dek, kek)
    assert unwrap_dek(wrapped, kek) == dek


def test_encrypt_decrypt_roundtrip():
    dek = generate_dek()
    plaintext = b"garmin-refresh-token-super-secret"
    ciphertext = encrypt(plaintext, dek)
    assert decrypt(ciphertext, dek) == plaintext


def test_ciphertext_is_not_plaintext():
    dek = generate_dek()
    plaintext = b"secret"
    assert encrypt(plaintext, dek) != plaintext
