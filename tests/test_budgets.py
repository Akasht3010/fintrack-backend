def test_create_budget(client, auth_headers):
    headers, _ = auth_headers
    res = client.post("/api/budgets", json={"category": "food", "limit_amount": 5000, "period": "monthly"}, headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["limit_amount"] == 5000
    assert body["spent_amount"] == 0


def test_create_budget_rejects_unknown_category(client, auth_headers):
    headers, _ = auth_headers
    res = client.post("/api/budgets", json={"category": "not-real", "limit_amount": 5000, "period": "monthly"}, headers=headers)
    assert res.status_code == 400


def test_create_budget_rejects_a_second_budget_for_the_same_category_and_overlapping_period(client, auth_headers):
    headers, _ = auth_headers
    first = client.post("/api/budgets", json={"category": "food", "limit_amount": 5000, "period": "monthly"}, headers=headers)
    assert first.status_code == 200

    second = client.post("/api/budgets", json={"category": "food", "limit_amount": 3000, "period": "monthly"}, headers=headers)
    assert second.status_code == 409


def test_expired_budget_does_not_block_a_new_one_for_the_same_category(client, auth_headers):
    from datetime import datetime, timedelta
    from app.config.database import SessionLocal
    from app.models.budget import Budget

    headers, user = auth_headers

    # An old "food" budget whose period ended well before now — invisible to
    # list_active_budgets, but under the old overlap check it could still
    # 409 a fresh budget the user can't see to delete.
    db = SessionLocal()
    try:
        past_end = datetime.utcnow() - timedelta(days=40)
        db.add(Budget(
            user_id=user["id"], category="food", limit_amount=1000, spent_amount=0,
            period="monthly", start_date=past_end - timedelta(days=30), end_date=past_end
        ))
        db.commit()
    finally:
        db.close()

    res = client.post("/api/budgets", json={"category": "food", "limit_amount": 5000, "period": "monthly"}, headers=headers)
    assert res.status_code == 200, res.text

    listed = client.get("/api/budgets", headers=headers).json()
    assert len(listed) == 1
    assert listed[0]["limit_amount"] == 5000


def test_different_categories_can_each_have_a_budget(client, auth_headers):
    headers, _ = auth_headers
    food = client.post("/api/budgets", json={"category": "food", "limit_amount": 5000, "period": "monthly"}, headers=headers)
    transport = client.post("/api/budgets", json={"category": "transport", "limit_amount": 2000, "period": "monthly"}, headers=headers)
    assert food.status_code == 200
    assert transport.status_code == 200


def test_budget_spend_reflects_matching_debit_transactions_only(client, auth_headers):
    headers, _ = auth_headers
    client.post("/api/budgets", json={"category": "food", "limit_amount": 5000, "period": "monthly"}, headers=headers)

    # Counts: a debit in the budgeted category
    client.post("/api/transactions", json={
        "amount": 300.0, "currency": "INR", "type": "debit", "category": "food",
        "merchant": "Cafe", "description": "lunch", "date": "2026-08-01T12:00:00", "source": "manual"
    }, headers=headers)
    # Doesn't count: a credit (refund) in the same category
    client.post("/api/transactions", json={
        "amount": 50.0, "currency": "INR", "type": "credit", "category": "food",
        "merchant": "Cafe", "description": "refund", "date": "2026-08-01T13:00:00", "source": "manual"
    }, headers=headers)
    # Doesn't count: a debit in a different category
    client.post("/api/transactions", json={
        "amount": 400.0, "currency": "INR", "type": "debit", "category": "transport",
        "merchant": "Cab", "description": "ride", "date": "2026-08-01T14:00:00", "source": "manual"
    }, headers=headers)

    res = client.get("/api/budgets", headers=headers)
    assert res.status_code == 200
    budgets = res.json()
    assert len(budgets) == 1
    assert budgets[0]["spent_amount"] == 300.0


def test_update_budget_limit(client, auth_headers):
    headers, _ = auth_headers
    created = client.post("/api/budgets", json={"category": "food", "limit_amount": 5000, "period": "monthly"}, headers=headers).json()
    res = client.patch(f"/api/budgets/{created['id']}", json={"limit_amount": 7000}, headers=headers)
    assert res.status_code == 200
    assert res.json()["limit_amount"] == 7000


def test_delete_budget(client, auth_headers):
    headers, _ = auth_headers
    created = client.post("/api/budgets", json={"category": "food", "limit_amount": 5000, "period": "monthly"}, headers=headers).json()
    res = client.delete(f"/api/budgets/{created['id']}", headers=headers)
    assert res.status_code == 200

    list_res = client.get("/api/budgets", headers=headers)
    assert list_res.json() == []


def test_budgets_are_scoped_to_the_authenticated_user(client, auth_headers, signup):
    headers, _ = auth_headers
    client.post("/api/budgets", json={"category": "food", "limit_amount": 5000, "period": "monthly"}, headers=headers)

    other_token, _ = signup(email="other-budgeter@example.com", phone="9876543296")
    other_headers = {"Authorization": f"Bearer {other_token}"}
    res = client.get("/api/budgets", headers=other_headers)
    assert res.json() == []
