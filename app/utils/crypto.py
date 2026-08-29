import os
from functools import lru_cache

from cryptography.fernet import Fernet


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    # Lazy, not module-level: raising only when a secret is actually
    # encrypted/decrypted (rather than at import time, like SECRET_KEY) means
    # a deploy that hasn't set this yet doesn't crash the whole app — only
    # the Gmail-linking paths that need it.
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY environment variable must be set to store or read encrypted "
            "secrets (e.g. Gmail refresh tokens). Generate one with:\n"
            '  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    return Fernet(key.encode())


def encrypt(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _get_fernet().decrypt(value.encode()).decode()
