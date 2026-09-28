import base64
import hashlib
import secrets

import bcrypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


def encryption_key() -> bytes:
    raw = get_settings().encrypt_key.encode("utf-8")
    if len(raw) != 32:
        raise RuntimeError("SQLCHAT_ENCRYPT_KEY must contain exactly 32 UTF-8 bytes")
    return raw


def encrypt(value: str) -> str:
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(encryption_key()).encrypt(nonce, value.encode(), None)
    return base64.b64encode(nonce + ciphertext).decode()


def decrypt(value: str) -> str:
    raw = base64.b64decode(value, validate=True)
    if len(raw) < 28:
        raise ValueError("Encrypted credential is incomplete")
    return AESGCM(encryption_key()).decrypt(raw[:12], raw[12:], None).decode()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
