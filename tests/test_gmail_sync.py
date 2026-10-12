from unittest.mock import patch

from app.config.database import SessionLocal
from app.models.user import User
from app.utils.crypto import encrypt


def _connect_gmail(user_id):
    db = SessionLocal()
    user = db.get(User, user_id)
    user.gmail_connected = True
    user.gmail_refresh_token = encrypt("fake-refresh-token")
    db.commit()
    db.close()


def test_sync_failure_does_not_leak_exception_text(client, auth_headers):
    headers, user = auth_headers
    _connect_gmail(user["id"])

    with patch("app.api.gmail.gmail_service.search_bank_emails",
               side_effect=Exception("upstream 10.0.0.7 said: internal-detail")):
        res = client.post("/api/gmail/sync", headers=headers)

    assert res.status_code == 502
    assert "internal-detail" not in res.text
    assert "10.0.0.7" not in res.text
