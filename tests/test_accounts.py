def test_create_account(client, auth_headers):
    headers, _ = auth_headers
    res = client.post("/api/accounts", json={
        "name": "Main Bank", "type": "bank", "currency": "INR", "opening_balance": 1000
    }, headers=headers)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["balance"] == 1000
    assert body["is_archived"] is False


def test_account_balance_increases_with_credits_and_decreases_with_debits(client, auth_headers):
    headers, _ = auth_headers
    account = client.post("/api/accounts", json={
        "name": "Main Bank", "type": "bank", "currency": "INR", "opening_balance": 1000
    }, headers=headers).json()

    client.post("/api/transactions", json={
        "amount": 500.0, "currency": "INR", "type": "credit", "category": "other",
        "merchant": "Employer", "description": "salary", "date": "2026-08-01T09:00:00",
        "source": "manual", "account_id": account["id"]
    }, headers=headers)
    client.post("/api/transactions", json={
        "amount": 200.0, "currency": "INR", "type": "debit", "category": "food",
        "merchant": "Cafe", "description": "lunch", "date": "2026-08-01T12:00:00",
        "source": "manual", "account_id": account["id"]
    }, headers=headers)

    res = client.get("/api/accounts", headers=headers)
    updated = res.json()[0]
    assert updated["balance"] == 1000 + 500 - 200


def test_credit_card_balance_moves_opposite_to_asset_accounts(client, auth_headers):
    """A credit card's `balance` is what's owed: a purchase (debit) increases
    it, a payment (credit) decreases it — the reverse of a bank account."""
    headers, _ = auth_headers
    card = client.post("/api/accounts", json={
        "name": "Visa", "type": "credit_card", "currency": "INR", "opening_balance": 0
    }, headers=headers).json()

    client.post("/api/transactions", json={
        "amount": 1500.0, "currency": "INR", "type": "debit", "category": "shopping",
        "merchant": "Store", "description": "purchase", "date": "2026-08-01T12:00:00",
        "source": "manual", "account_id": card["id"]
    }, headers=headers)

    res = client.get("/api/accounts", headers=headers)
    assert res.json()[0]["balance"] == 1500.0


def test_net_worth_subtracts_credit_card_balance_from_bank_balance(client, auth_headers):
    headers, _ = auth_headers
    bank = client.post("/api/accounts", json={
        "name": "Bank", "type": "bank", "currency": "INR", "opening_balance": 10000
    }, headers=headers).json()
    card = client.post("/api/accounts", json={
        "name": "Card", "type": "credit_card", "currency": "INR", "opening_balance": 0
    }, headers=headers).json()
    client.post("/api/transactions", json={
        "amount": 3000.0, "currency": "INR", "type": "debit", "category": "shopping",
        "merchant": "Store", "description": "purchase", "date": "2026-08-01T12:00:00",
        "source": "manual", "account_id": card["id"]
    }, headers=headers)

    res = client.get("/api/accounts/net-worth", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total_assets"] == 10000
    assert body["total_liabilities"] == 3000
    assert body["net_worth"] == 7000


def test_archived_accounts_are_excluded_from_the_default_list(client, auth_headers):
    headers, _ = auth_headers
    account = client.post("/api/accounts", json={
        "name": "Old Wallet", "type": "wallet", "currency": "INR", "opening_balance": 100
    }, headers=headers).json()
    client.patch(f"/api/accounts/{account['id']}", json={"is_archived": True}, headers=headers)

    res = client.get("/api/accounts", headers=headers)
    assert res.json() == []

    included = client.get("/api/accounts", params={"include_archived": True}, headers=headers)
    assert len(included.json()) == 1


def test_deleting_an_account_still_referenced_by_a_transaction_is_blocked(client, auth_headers):
    headers, _ = auth_headers
    account = client.post("/api/accounts", json={
        "name": "Bank", "type": "bank", "currency": "INR", "opening_balance": 0
    }, headers=headers).json()
    client.post("/api/transactions", json={
        "amount": 100.0, "currency": "INR", "type": "debit", "category": "food",
        "merchant": "Cafe", "description": "lunch", "date": "2026-08-01T12:00:00",
        "source": "manual", "account_id": account["id"]
    }, headers=headers)

    res = client.delete(f"/api/accounts/{account['id']}", headers=headers)
    assert res.status_code == 409


def test_deleting_an_unused_account_succeeds(client, auth_headers):
    headers, _ = auth_headers
    account = client.post("/api/accounts", json={
        "name": "Unused", "type": "cash", "currency": "INR", "opening_balance": 0
    }, headers=headers).json()

    res = client.delete(f"/api/accounts/{account['id']}", headers=headers)
    assert res.status_code == 200
    assert client.get("/api/accounts", headers=headers).json() == []


def test_create_transaction_rejects_currency_mismatch_with_its_account(client, auth_headers):
    """A transaction's currency has to match its account's — compute_balance
    sums a linked account's transactions in the account's own currency
    without converting, so a mismatch would otherwise silently corrupt it."""
    headers, _ = auth_headers
    account = client.post("/api/accounts", json={
        "name": "USD Card", "type": "credit_card", "currency": "USD", "opening_balance": 0
    }, headers=headers).json()

    res = client.post("/api/transactions", json={
        "amount": 100.0, "currency": "INR", "type": "debit", "category": "shopping",
        "merchant": "Amazon", "description": "order", "date": "2026-08-01T12:00:00",
        "source": "manual", "account_id": account["id"]
    }, headers=headers)
    assert res.status_code == 400
    assert "currency" in res.json()["detail"].lower()


def test_update_transaction_rejects_currency_mismatch_with_its_account(client, auth_headers):
    headers, _ = auth_headers
    usd_account = client.post("/api/accounts", json={
        "name": "USD Card", "type": "credit_card", "currency": "USD", "opening_balance": 0
    }, headers=headers).json()
    inr_account = client.post("/api/accounts", json={
        "name": "INR Bank", "type": "bank", "currency": "INR", "opening_balance": 0
    }, headers=headers).json()
    transaction = client.post("/api/transactions", json={
        "amount": 100.0, "currency": "INR", "type": "debit", "category": "shopping",
        "merchant": "Amazon", "description": "order", "date": "2026-08-01T12:00:00",
        "source": "manual", "account_id": inr_account["id"]
    }, headers=headers).json()

    res = client.patch(f"/api/transactions/{transaction['id']}", json={
        "account_id": usd_account["id"]
    }, headers=headers)
    assert res.status_code == 400
    assert "currency" in res.json()["detail"].lower()
