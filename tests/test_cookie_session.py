from app.utils.auth import SESSION_COOKIE
from app.utils.oauth_state import create_state

COOKIE_MODE = {"X-Auth-Transport": "cookie"}


def _cookie_login(client, signup, captured_otp, email="web@example.com"):
    """Sign up (bearer, via the fixture), then log in again the way the web
    build does — returns the verify-otp response."""
    signup(email=email, phone="9876543210", password="TestPass123!")
    client.cookies.clear()
    pending = client.post("/api/auth/login", json={"identifier": email, "password": "TestPass123!"}).json()
    return client.post("/api/auth/verify-otp", json={
        "pending_token": pending["pending_token"], "code": captured_otp["code"]
    }, headers=COOKIE_MODE)


def _set_cookie_header(res) -> str:
    return "; ".join(v for k, v in res.headers.multi_items() if k.lower() == "set-cookie")


def test_cookie_mode_login_sets_an_httponly_cookie_and_keeps_the_token_out_of_the_body(client, signup, captured_otp):
    res = _cookie_login(client, signup, captured_otp)
    assert res.status_code == 200, res.text
    assert res.json()["access_token"] is None
    cookie = _set_cookie_header(res)
    assert f"{SESSION_COOKIE}=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/api" in cookie

    # The cookie alone authenticates reads.
    assert client.get("/api/auth/me").json()["email"] == "web@example.com"


def test_bearer_clients_get_no_cookie(client, signup, captured_otp):
    signup(email="mobile@example.com", phone="9876543210", password="TestPass123!")
    client.cookies.clear()
    pending = client.post("/api/auth/login", json={"identifier": "mobile@example.com", "password": "TestPass123!"}).json()
    res = client.post("/api/auth/verify-otp", json={"pending_token": pending["pending_token"], "code": captured_otp["code"]})
    assert res.json()["access_token"]
    assert SESSION_COOKIE not in _set_cookie_header(res)


def test_cookie_authed_writes_need_the_transport_header(client, signup, captured_otp):
    """CSRF defense in depth: a cross-site form can send the cookie (were
    SameSite ever relaxed) but can't set a custom header."""
    _cookie_login(client, signup, captured_otp)
    payload = {"name": "Groceries", "icon": "🛒", "type": "expense"}

    assert client.post("/api/categories", json=payload).status_code == 403
    assert client.post("/api/categories", json=payload, headers=COOKIE_MODE).status_code == 201


def test_cookie_mode_refresh_renews_the_cookie_without_exposing_the_token(client, signup, captured_otp):
    _cookie_login(client, signup, captured_otp)
    res = client.post("/api/auth/refresh", headers=COOKIE_MODE)
    assert res.status_code == 200
    assert res.json() == {"access_token": None}
    assert f"{SESSION_COOKIE}=" in _set_cookie_header(res)


def test_logout_clears_the_cookie_and_revokes_the_session(client, signup, captured_otp):
    _cookie_login(client, signup, captured_otp)
    old_cookie = client.cookies.get(SESSION_COOKIE)

    assert client.post("/api/auth/logout", headers=COOKIE_MODE).status_code == 200
    assert client.cookies.get(SESSION_COOKIE) is None
    assert client.get("/api/auth/me").status_code == 401
    # Even if the old cookie value were replayed, it's revoked.
    client.cookies.set(SESSION_COOKIE, old_cookie, path="/api")
    assert client.get("/api/auth/me").status_code == 401


def test_clear_session_drops_a_dead_cookie_without_auth(client):
    res = client.post("/api/auth/clear-session")
    assert res.status_code == 200
    cookie = _set_cookie_header(res)
    assert f'{SESSION_COOKIE}=""' in cookie and "Max-Age=0" in cookie and "Path=/api" in cookie


def test_google_exchange_in_cookie_mode_sets_the_cookie(client, signup):
    token, _ = signup(email="g@example.com", phone="9876543210")
    client.cookies.clear()
    code = create_state({"access_token": token})
    res = client.post("/api/auth/google/exchange", json={"code": code}, headers=COOKIE_MODE)
    assert res.status_code == 200
    assert res.json()["access_token"] is None
    assert client.get("/api/auth/me").json()["email"] == "g@example.com"


def test_no_credentials_is_a_401(client):
    assert client.get("/api/auth/me").status_code == 401
