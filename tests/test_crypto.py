from app.config.database import SessionLocal
from app.config.init_db import encrypt_plaintext_gmail_tokens
from app.models.user import User
from app.services.user_service import UserService
from app.utils.crypto import decrypt, encrypt


def test_encrypt_decrypt_round_trip():
    original = "1//0gLnFakeRefreshTokenValue"
    ciphertext = encrypt(original)
    assert ciphertext != original
    assert decrypt(ciphertext) == original


def test_update_gmail_token_stores_ciphertext_not_plaintext(client, signup):
    _, user = signup(email="gmail-user@example.com", phone="9876543212")

    UserService.update_gmail_token(SessionLocal(), user["id"], "raw-refresh-token-value")

    db = SessionLocal()
    try:
        stored = db.query(User).filter(User.id == user["id"]).first()
        assert stored.gmail_refresh_token != "raw-refresh-token-value"
        assert decrypt(stored.gmail_refresh_token) == "raw-refresh-token-value"
    finally:
        db.close()


def test_encrypt_plaintext_gmail_tokens_migration_is_idempotent(client, signup):
    _, user = signup(email="legacy-gmail-user@example.com", phone="9876543213")

    # Simulate a token written before encryption-at-rest existed.
    db = SessionLocal()
    try:
        stored = db.query(User).filter(User.id == user["id"]).first()
        stored.gmail_refresh_token = "legacy-plaintext-token"
        db.commit()
    finally:
        db.close()

    encrypt_plaintext_gmail_tokens()

    db = SessionLocal()
    try:
        stored = db.query(User).filter(User.id == user["id"]).first()
        assert stored.gmail_refresh_token != "legacy-plaintext-token"
        assert decrypt(stored.gmail_refresh_token) == "legacy-plaintext-token"
        once_encrypted = stored.gmail_refresh_token
    finally:
        db.close()

    # Running it again must not double-encrypt an already-encrypted token.
    encrypt_plaintext_gmail_tokens()

    db = SessionLocal()
    try:
        stored = db.query(User).filter(User.id == user["id"]).first()
        assert stored.gmail_refresh_token == once_encrypted
        assert decrypt(stored.gmail_refresh_token) == "legacy-plaintext-token"
    finally:
        db.close()
