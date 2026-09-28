import base64
import hashlib
import secrets

import bcrypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


def encrypt(value: str) -> str:
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(get_settings().encrypt_key.encode()).encrypt(nonce, value.encode(), None)
    return base64.b64encode(nonce + ciphertext).decode()


def decrypt(value: str) -> str:
    raw = base64.b64decode(value, validate=True)
    return AESGCM(get_settings().encrypt_key.encode()).decrypt(raw[:12], raw[12:], None).decode()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
