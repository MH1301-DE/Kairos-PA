import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def generate_dek() -> bytes:
    return os.urandom(32)


def wrap_dek(dek: bytes, kek: bytes) -> bytes:
    """AES-256-GCM wrap. Returns nonce||ciphertext."""
    nonce = os.urandom(12)
    return nonce + AESGCM(kek).encrypt(nonce, dek, None)


def unwrap_dek(wrapped: bytes, kek: bytes) -> bytes:
    return AESGCM(kek).decrypt(wrapped[:12], wrapped[12:], None)


def encrypt(plaintext: bytes, dek: bytes) -> bytes:
    """AES-256-GCM encrypt. Returns nonce||ciphertext."""
    nonce = os.urandom(12)
    return nonce + AESGCM(dek).encrypt(nonce, plaintext, None)


def decrypt(ciphertext: bytes, dek: bytes) -> bytes:
    return AESGCM(dek).decrypt(ciphertext[:12], ciphertext[12:], None)


def kek_from_settings(b64_key: str) -> bytes:
    return base64.b64decode(b64_key)
