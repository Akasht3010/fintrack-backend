import app.utils.admin_auth as admin_auth
from app.utils.rate_limit import limiter


def test_admin_health_rejects_wrong_key(client, monkeypatch):
    monkeypatch.setattr(admin_auth, "ADMIN_API_KEY", "test-admin-key")
    res = client.get("/api/admin/health", headers={"X-Admin-Key": "wrong"})
    assert res.status_code == 401


def test_admin_health_succeeds_with_correct_key(client, monkeypatch):
    monkeypatch.setattr(admin_auth, "ADMIN_API_KEY", "test-admin-key")
    res = client.get("/api/admin/health", headers={"X-Admin-Key": "test-admin-key"})
    assert res.status_code == 200, res.text


def test_repeated_wrong_admin_key_attempts_are_rate_limited(client, monkeypatch):
    """Regression test for B-P2-4: the admin key check had no throttle at
    all, so a wrong key could be retried as fast as the network allowed.
    The rate limit is applied to require_admin_key itself (not the route)
    so a wrong key is throttled even though it never reaches the route body
    — a @limiter.limit() on the route only runs once dependencies, this one
    included, have already succeeded."""
    monkeypatch.setattr(admin_auth, "ADMIN_API_KEY", "test-admin-key")
    monkeypatch.setattr(limiter, "enabled", True)
    limiter.reset()

    last_res = None
    for _ in range(35):
        last_res = client.get("/api/admin/health", headers={"X-Admin-Key": "wrong"})

    assert last_res.status_code == 429, last_res.text
    assert "detail" in last_res.json()
