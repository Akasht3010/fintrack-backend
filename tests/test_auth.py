from unittest.mock import MagicMock, patch

from app.config.database import SessionLocal
from app.models.user import User
from app.services.user_service import UserService
from app.utils.oauth_state import create_state


def test_users_phone_has_a_db_level_unique_constraint(client):
    """UserService.create_user's pre-insert uniqueness check has a race: two
    concurrent signups with the same phone can both pass it before either
    commits. A real DB constraint (not just the app-level check) is what
    actually closes that — bypass the service layer and insert straight via
    the ORM to prove the constraint itself exists, independent of the check."""
    import pytest
    from sqlalchemy.exc import IntegrityError
    from app.config.database import SessionLocal
    from app.models.user import User
    from app.utils.auth import hash_password

    db = SessionLocal()
    try:
        db.add(User(name="A", email="dup-a@example.com", phone="9876543299", password_hash=hash_password("x")))
        db.commit()

        db.add(User(name="B", email="dup-b@example.com", phone="9876543299", password_hash=hash_password("x")))
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_signup_emails_an_otp_and_does_not_return_an_access_token(client, captured_otp):
    res = client.post("/api/auth/signup", json={
        "name": "Alice", "email": "alice@example.com", "phone": "9876543210",
        "password": "TestPass123!", "confirm_password": "TestPass123!"
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert "access_token" not in body
    assert body["pending_token"]
    assert body["email_hint"] == "al***@example.com"
    assert captured_otp["code"] and len(captured_otp["code"]) == 6


def test_signup_otp_round_trip_verifies_the_email_and_issues_a_session(client, captured_otp):
    res = client.post("/api/auth/signup", json={
        "name": "Alice", "email": "alice@example.com", "phone": "9876543210",
        "password": "TestPass123!", "confirm_password": "TestPass123!"
    })
    verify_res = client.post("/api/auth/verify-otp", json={
        "pending_token": res.json()["pending_token"], "code": captured_otp["code"]
    })
    assert verify_res.status_code == 200, verify_res.text
    assert verify_res.json()["user"]["phone"] == "9876543210"

    db = SessionLocal()
    try:
        assert db.query(User).filter(User.email == "alice@example.com").one().email_verified is True
    finally:
        db.close()


def test_google_sign_in_into_an_unverified_signup_drops_its_password_and_sessions(client, captured_otp):
    """Pre-account-takeover: someone signs up with an address they don't own
    and never verifies it. When the address's real owner later signs in
    with Google, they must not inherit a password (or a session) that the
    squatter set."""
    client.post("/api/auth/signup", json={
        "name": "Squatter", "email": "victim@example.com", "phone": "9876543210",
        "password": "SquatterPass1!", "confirm_password": "SquatterPass1!"
    })

    db = SessionLocal()
    try:
        before = db.query(User).filter(User.email == "victim@example.com").one()
        version_before = before.token_version
        user = UserService.find_or_create_google_user(
            db, email="victim@example.com", name="Victim", avatar=None, google_id="google-sub-1"
        )
        assert user.password_hash is None
        assert user.token_version == version_before + 1
        assert user.email_verified is True
    finally:
        db.close()

    login_res = client.post("/api/auth/login", json={"identifier": "victim@example.com", "password": "SquatterPass1!"})
    assert login_res.status_code == 400  # Google-only now; the squatter's password is gone


def test_google_sign_in_into_a_verified_account_keeps_its_password(client, signup):
    token, _ = signup(email="owner@example.com", phone="9876543210", password="OwnerPass123!")

    db = SessionLocal()
    try:
        user = UserService.find_or_create_google_user(
            db, email="owner@example.com", name="Owner", avatar=None, google_id="google-sub-2"
        )
        assert user.password_hash is not None
    finally:
        db.close()

    # Existing session untouched — nothing about this account was in doubt.
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_signup_rejects_mismatched_passwords(client):
    res = client.post("/api/auth/signup", json={
        "name": "Alice", "email": "alice@example.com", "phone": "9876543210",
        "password": "TestPass123!", "confirm_password": "Different123!"
    })
    assert res.status_code == 422


def test_signup_rejects_duplicate_email(client, signup):
    signup(email="dupe@example.com", phone="9876543210")
    res = client.post("/api/auth/signup", json={
        "name": "Bob", "email": "dupe@example.com", "phone": "9876543211",
        "password": "TestPass123!", "confirm_password": "TestPass123!"
    })
    assert res.status_code == 409


def test_signup_rejects_duplicate_phone(client, signup):
    signup(email="first@example.com", phone="9876543210")
    res = client.post("/api/auth/signup", json={
        "name": "Bob", "email": "second@example.com", "phone": "9876543210",
        "password": "TestPass123!", "confirm_password": "TestPass123!"
    })
    assert res.status_code == 409


def test_login_sends_otp_and_does_not_return_an_access_token(client, signup, captured_otp):
    signup(email="carol@example.com", phone="9876543210", password="TestPass123!")
    res = client.post("/api/auth/login", json={"identifier": "carol@example.com", "password": "TestPass123!"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert "pending_token" in body
    assert "access_token" not in body
    assert captured_otp["code"] and len(captured_otp["code"]) == 6


def test_login_rejects_wrong_password(client, signup):
    signup(email="dave@example.com", phone="9876543210", password="TestPass123!")
    res = client.post("/api/auth/login", json={"identifier": "dave@example.com", "password": "WrongPass123!"})
    assert res.status_code == 401


def test_login_rejects_unknown_identifier(client):
    # Same status/message as a wrong password (test_login_rejects_wrong_password)
    # — a distinguishable response here would leak which identifiers have an
    # account.
    res = client.post("/api/auth/login", json={"identifier": "nobody@example.com", "password": "whatever123"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Incorrect phone/email or password"


def test_login_unknown_identifier_and_wrong_password_return_identical_responses(client, signup):
    signup(email="judy@example.com", phone="9876543212", password="TestPass123!")
    wrong_password_res = client.post("/api/auth/login", json={"identifier": "judy@example.com", "password": "WrongPass123!"})
    unknown_identifier_res = client.post("/api/auth/login", json={"identifier": "nobody@example.com", "password": "WrongPass123!"})
    assert wrong_password_res.status_code == unknown_identifier_res.status_code == 401
    assert wrong_password_res.json() == unknown_identifier_res.json()


def test_full_login_otp_round_trip_issues_a_working_access_token(client, signup, captured_otp):
    signup(email="erin@example.com", phone="9876543210", password="TestPass123!")
    login_res = client.post("/api/auth/login", json={"identifier": "erin@example.com", "password": "TestPass123!"})
    pending_token = login_res.json()["pending_token"]

    verify_res = client.post("/api/auth/verify-otp", json={
        "pending_token": pending_token, "code": captured_otp["code"]
    })
    assert verify_res.status_code == 200, verify_res.text
    access_token = verify_res.json()["access_token"]

    me_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me_res.status_code == 200
    assert me_res.json()["email"] == "erin@example.com"


def test_verify_otp_rejects_wrong_code(client, signup, captured_otp):
    signup(email="frank@example.com", phone="9876543210", password="TestPass123!")
    login_res = client.post("/api/auth/login", json={"identifier": "frank@example.com", "password": "TestPass123!"})
    pending_token = login_res.json()["pending_token"]

    res = client.post("/api/auth/verify-otp", json={"pending_token": pending_token, "code": "000000"})
    assert res.status_code == 400


def test_verify_otp_locks_out_after_max_attempts(client, signup, captured_otp):
    signup(email="grace@example.com", phone="9876543210", password="TestPass123!")
    login_res = client.post("/api/auth/login", json={"identifier": "grace@example.com", "password": "TestPass123!"})
    pending_token = login_res.json()["pending_token"]

    # MAX_OTP_ATTEMPTS is 5 — five wrong guesses should exhaust it, and a
    # sixth attempt (even with the now-known-correct code) should still fail.
    for _ in range(5):
        res = client.post("/api/auth/verify-otp", json={"pending_token": pending_token, "code": "000000"})
        assert res.status_code == 400

    final_res = client.post("/api/auth/verify-otp", json={"pending_token": pending_token, "code": captured_otp["code"]})
    assert final_res.status_code == 400
    assert "too many" in final_res.json()["detail"].lower()


def test_verify_otp_rejects_a_login_pending_token_reused_for_password_reset_purpose(client, signup, captured_otp):
    signup(email="heidi@example.com", phone="9876543210", password="TestPass123!")
    login_res = client.post("/api/auth/login", json={"identifier": "heidi@example.com", "password": "TestPass123!"})
    pending_token = login_res.json()["pending_token"]

    # reset-password checks the token's purpose is "password_reset" — a
    # login-purpose token must be rejected, not silently accepted.
    res = client.post("/api/auth/reset-password", json={
        "pending_token": pending_token, "code": captured_otp["code"],
        "new_password": "NewPass123!", "confirm_new_password": "NewPass123!"
    })
    assert res.status_code == 401


def test_forgot_password_unknown_identifier_returns_same_shape_as_known(client, signup):
    signup(email="nadia@example.com", phone="9876543213", password="TestPass123!")
    known_res = client.post("/api/auth/forgot-password", json={"identifier": "nadia@example.com"})
    unknown_res = client.post("/api/auth/forgot-password", json={"identifier": "nobody@example.com"})
    assert known_res.status_code == unknown_res.status_code == 200
    assert set(known_res.json().keys()) == set(unknown_res.json().keys())


def test_forgot_password_unknown_identifier_pending_token_cannot_reset_anything(client):
    """The pending_token for an identifier with no matching account must
    behave like any other invalid/expired token at every downstream step —
    never a distinguishable 'account not found' that would undo the
    enumeration protection on the initial /forgot-password response."""
    res = client.post("/api/auth/forgot-password", json={"identifier": "nobody@example.com"})
    assert res.status_code == 200, res.text
    pending_token = res.json()["pending_token"]

    resend_res = client.post("/api/auth/resend-otp", json={"pending_token": pending_token})
    assert resend_res.status_code == 401
    assert resend_res.json()["detail"] == "Verification session expired. Please start over."

    reset_res = client.post("/api/auth/reset-password", json={
        "pending_token": pending_token, "code": "000000",
        "new_password": "NewPass123!", "confirm_new_password": "NewPass123!"
    })
    assert reset_res.status_code in (400, 401)


def test_get_me_requires_authentication(client):
    res = client.get("/api/auth/me")
    assert res.status_code in (401, 403)


def test_pending_token_cannot_authenticate_protected_routes(client, signup, captured_otp):
    """Regression test for a full auth bypass: a pending token (issued after
    step 1 of login, or after forgot-password with nothing but an email/phone
    — no password) must not work as a real access token. Mirrors the exact
    exploit: forgot-password with only an identifier, then try the returned
    pending_token against a protected route."""
    _, _user = signup(email="ivan@example.com", phone="9876543210", password="TestPass123!")

    forgot_res = client.post("/api/auth/forgot-password", json={"identifier": "ivan@example.com"})
    assert forgot_res.status_code == 200, forgot_res.text
    pending_token = forgot_res.json()["pending_token"]

    me_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {pending_token}"})
    assert me_res.status_code == 401

    delete_res = client.delete("/api/auth/me", headers={"Authorization": f"Bearer {pending_token}"})
    assert delete_res.status_code == 401

    # The account must still exist — the bypass, if present, would have let
    # the delete above actually go through.
    login_res = client.post("/api/auth/login", json={"identifier": "ivan@example.com", "password": "TestPass123!"})
    assert login_res.status_code == 200
    assert "pending_token" in login_res.json()


def test_get_me_rejects_garbage_token(client):
    res = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert res.status_code == 401


def test_update_me_rejects_email_already_used_by_another_account(client, signup):
    signup(email="ivan@example.com", phone="9876543210")
    token, _ = signup(email="judy@example.com", phone="9876543211")
    res = client.patch("/api/auth/me", json={"email": "ivan@example.com"}, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 409


def test_update_me_changes_name(client, signup):
    token, _ = signup(email="kim@example.com", phone="9876543210")
    res = client.patch("/api/auth/me", json={"name": "Kim Updated"}, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["name"] == "Kim Updated"


def test_delete_me_removes_the_account(client, signup):
    token, _ = signup(email="leo@example.com", phone="9876543210")
    headers = {"Authorization": f"Bearer {token}"}
    res = client.delete("/api/auth/me", headers=headers)
    assert res.status_code == 200

    me_res = client.get("/api/auth/me", headers=headers)
    assert me_res.status_code == 401


def test_delete_me_also_removes_the_users_transactions(client, signup):
    token, _user = signup(email="mallory@example.com", phone="9876543210")
    headers = {"Authorization": f"Bearer {token}"}
    txn_res = client.post("/api/transactions", json={
        "amount": 100.0, "currency": "INR", "type": "debit", "category": "food",
        "merchant": "Test Cafe", "description": "lunch", "date": "2026-08-01T12:00:00",
        "source": "manual"
    }, headers=headers)
    assert txn_res.status_code == 200, txn_res.text

    delete_res = client.delete("/api/auth/me", headers=headers)
    assert delete_res.status_code == 200

    # Re-signing up with the same email should now succeed — proves the old
    # row (and anything FK-adjacent to it) is actually gone, not just
    # unreachable via the deleted session's token.
    resignup = client.post("/api/auth/signup", json={
        "name": "Mallory Again", "email": "mallory@example.com", "phone": "9876543210",
        "password": "TestPass123!", "confirm_password": "TestPass123!"
    })
    assert resignup.status_code == 200, resignup.text


def test_refresh_issues_a_new_working_token(client, signup):
    token, _ = signup(email="nolan@example.com", phone="9876543210")
    res = client.post("/api/auth/refresh", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    new_token = res.json()["access_token"]

    me_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert me_res.status_code == 200
    assert me_res.json()["email"] == "nolan@example.com"


def test_logout_invalidates_the_token_that_called_it(client, signup):
    token, _ = signup(email="oscar@example.com", phone="9876543210")
    headers = {"Authorization": f"Bearer {token}"}

    logout_res = client.post("/api/auth/logout", headers=headers)
    assert logout_res.status_code == 200, logout_res.text

    me_res = client.get("/api/auth/me", headers=headers)
    assert me_res.status_code == 401


def test_logout_invalidates_every_outstanding_token_not_just_the_caller(client, signup):
    """Regression test for B-P0-1: logout has to be "log out everywhere" —
    a second, still-unexpired token minted before logout (e.g. another
    device, or one grabbed via /refresh) must stop working too."""
    token, _ = signup(email="peggy@example.com", phone="9876543210")

    refresh_res = client.post("/api/auth/refresh", headers={"Authorization": f"Bearer {token}"})
    other_token = refresh_res.json()["access_token"]

    client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})

    me_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {other_token}"})
    assert me_res.status_code == 401


def test_pre_revocation_token_without_tv_still_works_until_logout(client, signup):
    """Tokens minted before token_version existed have no "tv" claim — they
    must keep working across the deploy (not log everyone out), yet still
    die on the next logout like any other token."""
    from app.utils.auth import create_access_token

    token, user = signup(email="legacy@example.com", phone="9876543210")
    legacy = create_access_token(data={"sub": user["id"]})
    headers = {"Authorization": f"Bearer {legacy}"}

    assert client.get("/api/auth/me", headers=headers).status_code == 200

    client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_refresh_after_logout_is_rejected(client, signup):
    token, _ = signup(email="quinn@example.com", phone="9876543210")
    client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})

    res = client.post("/api/auth/refresh", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401


def test_password_reset_invalidates_tokens_issued_before_it(client, signup, captured_otp):
    """Regression test for B-P0-1: previously, resetting a password changed
    password_hash but left every outstanding access token (e.g. one an
    attacker stole before the reset) valid until its natural expiry."""
    old_token, _ = signup(email="rachel@example.com", phone="9876543210", password="OldPass123!")

    forgot_res = client.post("/api/auth/forgot-password", json={"identifier": "rachel@example.com"})
    pending_token = forgot_res.json()["pending_token"]

    reset_res = client.post("/api/auth/reset-password", json={
        "pending_token": pending_token, "code": captured_otp["code"],
        "new_password": "NewPass123!", "confirm_new_password": "NewPass123!"
    })
    assert reset_res.status_code == 200, reset_res.text

    old_token_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    assert old_token_res.status_code == 401

    new_token = reset_res.json()["access_token"]
    new_token_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert new_token_res.status_code == 200


def test_google_callback_refuses_an_unverified_google_email(client, signup):
    signup(email="owner@example.com", phone="9876543210")
    state = create_state({"app_redirect_uri": "fintrack://auth-callback"})
    idinfo = {"email": "owner@example.com", "email_verified": False, "sub": "google-sub-3", "name": "X"}

    with patch("app.api.google_auth._build_flow", return_value=MagicMock()), \
         patch("app.api.google_auth.google_id_token.verify_oauth2_token", return_value=idinfo):
        res = client.get("/api/auth/google/callback", params={"code": "c", "state": state}, follow_redirects=False)

    assert res.status_code == 400
    db = SessionLocal()
    try:
        assert db.query(User).filter(User.email == "owner@example.com").one().google_id is None
    finally:
        db.close()
