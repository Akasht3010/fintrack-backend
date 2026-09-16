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


def test_google_exchange_returns_the_access_token_for_a_valid_code(client):
    """/callback puts a one-time code (not the real JWT) in the redirect URL
    — this is the app trading it for the real token afterward."""
    code = oauth_state.create_state({"access_token": "fake-jwt-for-test"})
    res = client.post("/api/auth/google/exchange", json={"code": code})
    assert res.status_code == 200, res.text
    assert res.json()["access_token"] == "fake-jwt-for-test"


def test_google_exchange_rejects_an_unknown_code(client):
    res = client.post("/api/auth/google/exchange", json={"code": "not-a-real-code"})
    assert res.status_code == 401


def test_google_exchange_code_is_single_use(client):
    code = oauth_state.create_state({"access_token": "fake-jwt-for-test"})
    first = client.post("/api/auth/google/exchange", json={"code": code})
    assert first.status_code == 200
    second = client.post("/api/auth/google/exchange", json={"code": code})
    assert second.status_code == 401


def test_gmail_link_token_requires_authentication(client):
    res = client.get("/api/gmail/link-token")
    assert res.status_code in (401, 403)


def test_gmail_authorize_rejects_an_unknown_link_token(client):
    res = client.get(
        "/api/gmail/authorize",
        params={"link_token": "not-a-real-token", "app_redirect_uri": "fintrack://gmail-callback"}
    )
    assert res.status_code == 401


def test_gmail_link_token_then_authorize_round_trips_the_users_id(client, auth_headers):
    headers, user = auth_headers
    link_res = client.get("/api/gmail/link-token", headers=headers)
    assert link_res.status_code == 200, link_res.text
    link_token = link_res.json()["link_token"]

    # follow_redirects=False: authorize redirects straight to Google, which
    # we can't (and shouldn't) actually reach in a test — just confirm the
    # link token was accepted and a redirect to Google was produced.
    authorize_res = client.get(
        "/api/gmail/authorize",
        params={"link_token": link_token, "app_redirect_uri": "fintrack://gmail-callback"},
        follow_redirects=False
    )
    assert authorize_res.status_code in (302, 307)

    # Single-use, same as the OAuth state nonce it's built on.
    replay_res = client.get(
        "/api/gmail/authorize",
        params={"link_token": link_token, "app_redirect_uri": "fintrack://gmail-callback"},
        follow_redirects=False
    )
    assert replay_res.status_code == 401
