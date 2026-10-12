import hashlib
import json
import secrets
import time

from app.config.database import SessionLocal
from app.models.oauth_state import OAuthState
from app.utils.crypto import decrypt, encrypt

# 10 minutes is generous for a user to complete Google's consent screen but
# short enough that a leaked/logged nonce isn't useful for long.
_STATE_TTL_SECONDS = 600

# Stored in the DB, not a module-level dict: Cloud Run runs up to several
# instances and scales to zero, so the instance that handles /callback (or
# /exchange) is often not the one that minted the nonce in /authorize.


def _hash(nonce: str) -> str:
    return hashlib.sha256(nonce.encode()).hexdigest()


def create_state(data: dict) -> str:
    """Generates a random, unguessable nonce bound server-side to `data`
    and returns it to send as the OAuth `state` param. The caller never
    gets to choose or influence what's actually stored — only Google
    round-trips the opaque nonce back to us — unlike embedding the payload
    directly in `state` (a redirect URI, or base64 JSON carrying a user id),
    which is forgeable and lets a crafted callback leak a token to an
    attacker-controlled redirect or attach an OAuth grant to an arbitrary
    account."""
    nonce = secrets.token_urlsafe(32)
    db = SessionLocal()
    try:
        _prune_expired(db)
        db.add(OAuthState(
            nonce_hash=_hash(nonce),
            payload=encrypt(json.dumps(data)),
            expires_at=time.time() + _STATE_TTL_SECONDS,
        ))
        db.commit()
    finally:
        db.close()
    return nonce


def consume_state(nonce: str) -> dict | None:
    """Single-use: returns the bound data and forgets it, or None if the
    nonce is unknown, expired, or already used (replay)."""
    db = SessionLocal()
    try:
        row = db.get(OAuthState, _hash(nonce))
        if row is None:
            return None
        payload, expires_at = row.payload, row.expires_at
        # The delete's rowcount, not the read above, decides who wins: two
        # instances racing on the same nonce can both read the row, but only
        # one delete removes it.
        deleted = db.query(OAuthState).filter(OAuthState.nonce_hash == row.nonce_hash).delete()
        db.commit()
        if deleted != 1 or time.time() > expires_at:
            return None
        return json.loads(decrypt(payload))
    finally:
        db.close()


def _prune_expired(db) -> None:
    db.query(OAuthState).filter(OAuthState.expires_at < time.time()).delete()
