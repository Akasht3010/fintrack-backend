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
    assert body["amount"] == 250.0
    assert body["category"] == "food"


def test_create_transaction_ignores_client_supplied_source_and_forces_manual(client, auth_headers):
    """The gmail/sms sync paths never go through this endpoint, so anything
    arriving here is manual by definition — a client claiming source="gmail"
    would otherwise impersonate a higher-trust import."""
    headers, payload = _make_txn(auth_headers, source="gmail")
    res = client.post("/api/transactions", json=payload, headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["source"] == "manual"


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
    the same message, independent of any app-level check-then-insert race."""
    headers, payload = _make_txn(auth_headers, raw_text="gmail:msg-123")
    first = client.post("/api/transactions", json=payload, headers=headers)
    assert first.status_code == 200

    headers, payload2 = _make_txn(auth_headers, raw_text="gmail:msg-123", amount=999.0)
    second = client.post("/api/transactions", json=payload2, headers=headers)
    assert second.status_code == 409


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
