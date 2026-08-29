import time

from app.utils import oauth_state


def test_create_and_consume_round_trips_the_bound_data():
    nonce = oauth_state.create_state({"user_id": 42, "app_redirect_uri": "fintrack://auth-callback"})
    assert oauth_state.consume_state(nonce) == {"user_id": 42, "app_redirect_uri": "fintrack://auth-callback"}


def test_consuming_twice_fails_the_second_time():
    """Single-use — a replayed callback (or an attacker who intercepted the
    first one) must not be able to reuse the same state."""
    nonce = oauth_state.create_state({"app_redirect_uri": "fintrack://auth-callback"})
    assert oauth_state.consume_state(nonce) is not None
    assert oauth_state.consume_state(nonce) is None


def test_unknown_nonce_returns_none():
    assert oauth_state.consume_state("not-a-real-nonce") is None


def test_expired_nonce_is_rejected():
    nonce = oauth_state.create_state({"app_redirect_uri": "fintrack://auth-callback"})
    # Simulate time passing past the TTL without waiting for it in real time.
    data, _ = oauth_state._pending_states[nonce]
    oauth_state._pending_states[nonce] = (data, time.time() - 1)
    assert oauth_state.consume_state(nonce) is None


def test_google_callback_rejects_an_unknown_state(client):
    res = client.get("/api/auth/google/callback", params={"code": "irrelevant", "state": "forged-state-value"})
    assert res.status_code == 400


def test_gmail_callback_rejects_an_unknown_state(client):
    res = client.get("/api/gmail/callback", params={"code": "irrelevant", "state": "forged-state-value"})
    assert res.status_code == 400
