from decimal import Decimal


def _make_txn(headers_and_user, **overrides):
    headers, _ = headers_and_user
    payload = {
        "amount": 250.0, "currency": "INR", "type": "debit", "category": "food",
        "merchant": "Test Cafe", "description": "lunch", "date": "2026-08-01T12:00:00",
        "source": "manual"
    }
    payload.update(overrides)
    return headers, payload


def test_create_transaction(client, auth_headers):
    headers, payload = _make_txn(auth_headers)
    res = client.post("/api/transactions", json=payload, headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert Decimal(body["amount"]) == Decimal("250.00")
    assert body["category"] == "food"


def test_create_transaction_ignores_client_supplied_source_and_forces_manual(client, auth_headers):
    """The gmail/sms sync paths never go through this endpoint, so anything
    arriving here is manual by definition — a client claiming source="gmail"
    would otherwise impersonate a higher-trust import."""
    headers, payload = _make_txn(auth_headers, source="gmail")
    res = client.post("/api/transactions", json=payload, headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["source"] == "manual"


def test_create_transaction_with_a_repeated_idempotency_key_is_rejected_not_duplicated(client, auth_headers):
    """Regression test for a retried create (e.g. a mobile client resending
    after a timeout, the first attempt having actually succeeded) — the
    second attempt must 409, not silently insert a second transaction."""
    headers, payload = _make_txn(auth_headers, idempotency_key="retry-key-1")
    first = client.post("/api/transactions", json=payload, headers=headers)
    assert first.status_code == 200, first.text

    second = client.post("/api/transactions", json=payload, headers=headers)
    assert second.status_code == 409

    listed = client.get("/api/transactions", headers=headers).json()
    assert listed["total"] == 1


def test_create_transaction_without_an_idempotency_key_allows_identical_transactions(client, auth_headers):
    """No key means no dedup — two genuinely separate manual entries that
    happen to look identical (e.g. two coffees at the same cafe) must both
    be allowed."""
    headers, payload = _make_txn(auth_headers)
    first = client.post("/api/transactions", json=payload, headers=headers)
    second = client.post("/api/transactions", json=payload, headers=headers)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    listed = client.get("/api/transactions", headers=headers).json()
    assert listed["total"] == 2


def test_create_transaction_rejects_unknown_category(client, auth_headers):
    headers, payload = _make_txn(auth_headers, category="not-a-real-category")
    res = client.post("/api/transactions", json=payload, headers=headers)
    assert res.status_code == 400


def test_create_transaction_rejects_zero_or_negative_amount(client, auth_headers):
    headers, payload = _make_txn(auth_headers, amount=0)
    assert client.post("/api/transactions", json=payload, headers=headers).status_code == 422

    headers, payload = _make_txn(auth_headers, amount=-50)
    assert client.post("/api/transactions", json=payload, headers=headers).status_code == 422


def test_create_transaction_rejects_amount_over_the_ceiling(client, auth_headers):
    headers, payload = _make_txn(auth_headers, amount=999_999_999)
    res = client.post("/api/transactions", json=payload, headers=headers)
    assert res.status_code == 422


def test_create_transaction_rejects_account_owned_by_someone_else(client, auth_headers, signup):
    headers, payload = _make_txn(auth_headers)
    other_token, _ = signup(email="other@example.com", phone="9876543299")
    other_account = client.post("/api/accounts", json={
        "name": "Other's Bank", "type": "bank", "currency": "INR", "opening_balance": 0
    }, headers={"Authorization": f"Bearer {other_token}"})
    assert other_account.status_code == 201

    payload["account_id"] = other_account.json()["id"]
    res = client.post("/api/transactions", json=payload, headers=headers)
    assert res.status_code == 400


def test_transactions_are_scoped_to_the_authenticated_user(client, auth_headers, signup):
    headers, payload = _make_txn(auth_headers)
    client.post("/api/transactions", json=payload, headers=headers)

    other_token, _ = signup(email="stranger@example.com", phone="9876543298")
    other_headers = {"Authorization": f"Bearer {other_token}"}
    res = client.get("/api/transactions", headers=other_headers)
    assert res.status_code == 200
    assert res.json()["total"] == 0


def test_list_transactions_filters_by_category(client, auth_headers):
    headers, payload = _make_txn(auth_headers, category="food")
    client.post("/api/transactions", json=payload, headers=headers)
    headers, payload2 = _make_txn(auth_headers, category="transport", merchant="Cab Co")
    client.post("/api/transactions", json=payload2, headers=headers)

    res = client.get("/api/transactions", params={"category": "transport"}, headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["transactions"][0]["merchant"] == "Cab Co"


def test_list_transactions_filters_by_search_query(client, auth_headers):
    headers, payload = _make_txn(auth_headers, merchant="Swiggy Order")
    client.post("/api/transactions", json=payload, headers=headers)
    headers, payload2 = _make_txn(auth_headers, merchant="Uber Ride")
    client.post("/api/transactions", json=payload2, headers=headers)

    res = client.get("/api/transactions", params={"q": "swiggy"}, headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert "Swiggy" in body["transactions"][0]["merchant"]


def test_duplicate_raw_text_import_is_rejected_at_the_db_level(client, auth_headers):
    """Mirrors what the Gmail/SMS sync endpoints rely on: the partial unique
    index on (user_id, raw_text) is what actually prevents double-importing
    the same message, independent of any app-level check-then-insert race.
    Inserted via the ORM — the import paths build rows directly, and the
    public create endpoint no longer accepts raw_text at all."""
    import pytest
    from sqlalchemy.exc import IntegrityError
    from app.config.database import SessionLocal
    from app.models.transaction import Transaction
    from app.utils.timezone import now_ist

    _, user = auth_headers
    def row(amount):
        return Transaction(user_id=user["id"], amount=amount, currency="INR", type="debit", category="food",
                           merchant="X", description="x", date=now_ist(), source="gmail", raw_text="gmail:msg-123")
    db = SessionLocal()
    try:
        db.add(row(250))
        db.commit()
        db.add(row(999))
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_create_ignores_client_supplied_raw_text(client, auth_headers):
    """A client claiming an import marker in advance would permanently block
    the real Gmail/SMS import of that message."""
    from app.config.database import SessionLocal
    from app.models.transaction import Transaction

    headers, payload = _make_txn(auth_headers, raw_text="gmail:future-msg")
    res = client.post("/api/transactions", json=payload, headers=headers)
    assert res.status_code == 200, res.text
    db = SessionLocal()
    try:
        assert db.get(Transaction, res.json()["id"]).raw_text is None
    finally:
        db.close()


def test_patch_with_null_for_a_required_field_is_a_422_not_a_500(client, auth_headers):
    headers, payload = _make_txn(auth_headers)
    txn = client.post("/api/transactions", json=payload, headers=headers).json()
    for field in ("category", "merchant", "description", "type", "amount"):
        res = client.patch(f"/api/transactions/{txn['id']}", json={field: None}, headers=headers)
        assert res.status_code == 422, (field, res.status_code, res.text)

    # account_id is the one field that may be cleared.
    res = client.patch(f"/api/transactions/{txn['id']}", json={"account_id": None}, headers=headers)
    assert res.status_code == 200, res.text


def test_text_fields_are_length_bounded(client, auth_headers):
    for field, size in (("merchant", 121), ("description", 501), ("category", 61)):
        headers, payload = _make_txn(auth_headers, **{field: "x" * size})
        assert client.post("/api/transactions", json=payload, headers=headers).status_code == 422, field
    headers, payload = _make_txn(auth_headers, merchant="")
    assert client.post("/api/transactions", json=payload, headers=headers).status_code == 422


def test_category_is_stored_in_its_canonical_spelling(client, auth_headers):
    """Matching is case-insensitive but budgets/insights compare exactly —
    "FOOD" stored as typed would silently miss the "food" budget."""
    headers, _ = auth_headers
    client.post("/api/budgets", json={"category": "Food", "limit_amount": 1000, "period": "monthly"}, headers=headers)
    from app.utils.timezone import now_ist
    _, payload = _make_txn(auth_headers, category="FOOD", date=now_ist().replace(hour=12, minute=0, second=0).isoformat())
    created = client.post("/api/transactions", json=payload, headers=headers).json()
    assert created["category"] == "food"

    budget = client.get("/api/budgets", headers=headers).json()[0]
    assert budget["category"] == "food"
    assert Decimal(budget["spent_amount"]) == Decimal("250")


def test_transactions_with_null_raw_text_do_not_collide(client, auth_headers):
    """The unique index has a `WHERE raw_text IS NOT NULL` clause specifically
    so ordinary manual entries (raw_text always null) never collide."""
    headers, payload = _make_txn(auth_headers)
    first = client.post("/api/transactions", json=payload, headers=headers)
    assert first.status_code == 200
    second = client.post("/api/transactions", json=payload, headers=headers)
    assert second.status_code == 200


def test_delete_transaction(client, auth_headers):
    headers, payload = _make_txn(auth_headers)
    created = client.post("/api/transactions", json=payload, headers=headers).json()
    res = client.delete(f"/api/transactions/{created['id']}", headers=headers)
    assert res.status_code == 200

    list_res = client.get("/api/transactions", headers=headers)
    assert list_res.json()["total"] == 0


def test_cannot_delete_another_users_transaction(client, auth_headers, signup):
    headers, payload = _make_txn(auth_headers)
    created = client.post("/api/transactions", json=payload, headers=headers).json()

    other_token, _ = signup(email="nosy@example.com", phone="9876543297")
    other_headers = {"Authorization": f"Bearer {other_token}"}
    res = client.delete(f"/api/transactions/{created['id']}", headers=other_headers)
    assert res.status_code == 404


def test_csv_export_neutralizes_formula_injection_in_merchant_and_description(client, auth_headers):
    """A merchant/description starting with =, +, -, or @ is interpreted as
    a formula by Excel/Sheets when the exported CSV is opened — most
    extraction patterns bound the captured text, but at least one doesn't,
    so this must hold regardless of how the value got there."""
    headers, payload = _make_txn(
        auth_headers,
        merchant="=cmd|'/c calc'!A1",
        description="+1;DDE",
    )
    client.post("/api/transactions", json=payload, headers=headers)

    res = client.get("/api/transactions/export", headers=headers)
    assert res.status_code == 200
    body = res.text
    assert "'=cmd|'/c calc'!A1" in body
    assert "'+1;DDE" in body
    # The raw, unprefixed formula must never appear as its own cell.
    assert ",=cmd" not in body
    assert ",+1;DDE" not in body
