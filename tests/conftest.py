import os

# Must be set before anything under app/ is imported — app.config.database
# raises at import time if DATABASE_URL is missing, and app.utils.auth does
# the same for SECRET_KEY. sqlite:///:memory: through database.py's
# non-Postgres branch already uses StaticPool, so every connection in the
# process shares the same in-memory DB rather than each getting its own
# (SQLite's normal :memory: behavior is connection-scoped).
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest-only"
os.environ.setdefault("CORS_ORIGINS", "")
os.environ.setdefault("OTP_EXPIRE_MINUTES", "5")
os.environ.setdefault("OTP_RESEND_COOLDOWN_SECONDS", "30")

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.config.database import Base, engine
from app.main import app


@pytest.fixture()
def client():
    # Entering TestClient's context runs the app's lifespan, which creates
    # tables + seeds default categories fresh each test; dropping afterward
    # keeps tests isolated (same shared in-memory DB across the process).
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def signup(client):
    """Create a user via the real signup endpoint and return (access_token, user_json)."""
    def _signup(email="test@example.com", phone="9999999999", password="TestPass123!", name="Test User"):
        res = client.post("/api/auth/signup", json={
            "name": name, "email": email, "phone": phone,
            "password": password, "confirm_password": password
        })
        assert res.status_code == 200, res.text
        body = res.json()
        return body["access_token"], body["user"]
    return _signup


@pytest.fixture()
def auth_headers(signup):
    """A ready-to-use Authorization header for a freshly signed-up user."""
    token, user = signup()
    return {"Authorization": f"Bearer {token}"}, user


@pytest.fixture()
def captured_otp():
    """Patches the actual email send so tests can read the code that would
    have been emailed, instead of needing a real SMTP server."""
    with patch("app.services.otp_service.send_otp_email") as mock_send:
        codes = {}

        def _capture(to_email, name, code):
            codes["code"] = code

        mock_send.side_effect = _capture
        yield codes
