import secrets
import time

# 10 minutes is generous for a user to complete Google's consent screen but
# short enough that a leaked/logged nonce isn't useful for long.
_STATE_TTL_SECONDS = 600

_pending_states: dict[str, tuple[dict, float]] = {}


def create_state(data: dict) -> str:
    """Generates a random, unguessable nonce bound server-side to `data`
    and returns it to send as the OAuth `state` param. The caller never
    gets to choose or influence what's actually stored — only Google
    round-trips the opaque nonce back to us — unlike embedding the payload
    directly in `state` (a redirect URI, or base64 JSON carrying a user id),
    which is forgeable and lets a crafted callback leak a token to an
    attacker-controlled redirect or attach an OAuth grant to an arbitrary
    account."""
    _prune_expired()
    nonce = secrets.token_urlsafe(32)
    _pending_states[nonce] = (data, time.time() + _STATE_TTL_SECONDS)
    return nonce


def consume_state(nonce: str) -> dict | None:
    """Single-use: returns the bound data and forgets it, or None if the
    nonce is unknown, expired, or already used (replay)."""
    entry = _pending_states.pop(nonce, None)
    if entry is None:
        return None
    data, expires_at = entry
    if time.time() > expires_at:
        return None
    return data


def _prune_expired() -> None:
    now = time.time()
    expired = [nonce for nonce, (_, expires_at) in _pending_states.items() if now > expires_at]
    for nonce in expired:
        _pending_states.pop(nonce, None)
