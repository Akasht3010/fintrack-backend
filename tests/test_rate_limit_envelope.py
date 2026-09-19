from app.utils.rate_limit import limiter


def test_429_response_uses_the_same_detail_envelope_as_every_other_error(client, monkeypatch):
    """Regression test for cross-repo contract issue #2: slowapi's default
    handler returns {"error": ...}, unlike every other error path in this API
    ({"detail": ...}) — the frontend's error parser only reads `detail` and
    silently drops the rate-limit message. Rate limiting is disabled under
    pytest by default (see conftest.py) so it doesn't trip on the test
    suite's own back-to-back requests; re-enabled here just for this test."""
    monkeypatch.setattr(limiter, "enabled", True)
    limiter.reset()

    last_res = None
    for _ in range(11):
        last_res = client.post("/api/auth/login", json={
            "identifier": "nobody@example.com", "password": "whatever123"
        })

    assert last_res.status_code == 429, last_res.text
    body = last_res.json()
    assert "detail" in body
    assert "error" not in body
    assert "rate limit" in body["detail"].lower()


def test_signup_is_rate_limited(client, monkeypatch):
    """Regression test for B-P1-1: /signup previously had no @limiter.limit
    at all, making it an unthrottled account-enumeration + spam surface
    (see test_signup_rejects_duplicate_email for the enumeration angle)."""
    monkeypatch.setattr(limiter, "enabled", True)
    limiter.reset()

    last_res = None
    for i in range(11):
        last_res = client.post("/api/auth/signup", json={
            "name": "Spammer", "email": f"spam{i}@example.com", "phone": f"90000000{i:02d}",
            "password": "TestPass123!", "confirm_password": "TestPass123!"
        })

    assert last_res.status_code == 429, last_res.text
    assert "detail" in last_res.json()
