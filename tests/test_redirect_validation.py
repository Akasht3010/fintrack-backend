import pytest
from fastapi import HTTPException

from app.utils.redirect_validation import validate_app_redirect_uri


def test_native_scheme_is_allowed():
    validate_app_redirect_uri("fintrack://auth-callback", callback_path="auth-callback")


def test_native_scheme_for_a_different_callback_path_is_rejected():
    """fintrack://auth-callback is not a valid redirect for the gmail-connect
    flow, and vice versa — each flow only trusts its own landing route."""
    with pytest.raises(HTTPException) as exc_info:
        validate_app_redirect_uri("fintrack://auth-callback", callback_path="gmail-callback")
    assert exc_info.value.status_code == 400


def test_expo_go_dev_redirect_is_allowed_outside_production(monkeypatch):
    monkeypatch.setattr("app.utils.redirect_validation._ENV", "development")
    validate_app_redirect_uri("exp://192.168.1.50:8081/--/auth-callback", callback_path="auth-callback")


def test_expo_go_dev_redirect_is_rejected_in_production(monkeypatch):
    monkeypatch.setattr("app.utils.redirect_validation._ENV", "production")
    with pytest.raises(HTTPException) as exc_info:
        validate_app_redirect_uri("exp://192.168.1.50:8081/--/auth-callback", callback_path="auth-callback")
    assert exc_info.value.status_code == 400


def test_web_origin_in_cors_allowlist_is_allowed(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://app.fintrack.example,https://other.example")
    validate_app_redirect_uri("https://app.fintrack.example/auth-callback", callback_path="auth-callback")


def test_web_origin_not_in_cors_allowlist_is_rejected(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://app.fintrack.example")
    with pytest.raises(HTTPException) as exc_info:
        validate_app_redirect_uri("https://evil.example/auth-callback", callback_path="auth-callback")
    assert exc_info.value.status_code == 400


def test_attacker_controlled_host_is_rejected():
    """The actual exploit from the 2026-10-07 review: an attacker-hosted
    collector disguised by a path that merely ends in the callback name."""
    with pytest.raises(HTTPException) as exc_info:
        validate_app_redirect_uri("https://attacker.example/collect", callback_path="auth-callback")
    assert exc_info.value.status_code == 400


def test_javascript_scheme_is_rejected():
    with pytest.raises(HTTPException) as exc_info:
        validate_app_redirect_uri("javascript:alert(1)", callback_path="auth-callback")
    assert exc_info.value.status_code == 400


def test_google_authorize_rejects_an_unallowlisted_redirect(client):
    res = client.get(
        "/api/auth/google/authorize",
        params={"app_redirect_uri": "https://attacker.example/collect"},
        follow_redirects=False
    )
    assert res.status_code == 400


def test_google_authorize_accepts_the_native_redirect(client):
    res = client.get(
        "/api/auth/google/authorize",
        params={"app_redirect_uri": "fintrack://auth-callback"},
        follow_redirects=False
    )
    assert res.status_code in (302, 307)


def test_gmail_authorize_rejects_an_unallowlisted_redirect(client, auth_headers):
    headers, _ = auth_headers
    link_token = client.get("/api/gmail/link-token", headers=headers).json()["link_token"]

    res = client.get(
        "/api/gmail/authorize",
        params={"link_token": link_token, "app_redirect_uri": "https://attacker.example/collect"},
        follow_redirects=False
    )
    assert res.status_code == 400

    # The link token must not be burned by a request that never passed
    # redirect validation — otherwise an attacker who merely guesses or
    # observes a victim's in-flight link_token could grief it with one bad
    # request, forcing the real user to restart the connect flow.
    replay = client.get(
        "/api/gmail/authorize",
        params={"link_token": link_token, "app_redirect_uri": "fintrack://gmail-callback"},
        follow_redirects=False
    )
    assert replay.status_code in (302, 307)
