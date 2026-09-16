import json
from decimal import Decimal

from app.config.database import SessionLocal
from app.models.budget import Budget
from app.models.transaction import Transaction
from app.utils.timezone import now_ist


def _in_period_date(hour: int = 12) -> str:
    """A naive ISO timestamp guaranteed to fall inside the current monthly
    budget window (same helper as tests/test_budgets.py)."""
    return now_ist().replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()


def test_transaction_amount_is_stored_as_decimal_not_float(client, auth_headers):
    """Regression test for the money-as-float bug: the DB column (and every
    Python-side read of it) must be exact Decimal, not a binary float that
    can't represent values like 0.10 exactly."""
    headers, _ = auth_headers
    res = client.post("/api/transactions", json={
        "amount": 19.99, "currency": "INR", "type": "debit", "category": "food",
        "merchant": "Cafe", "description": "lunch", "date": "2026-08-01T12:00:00",
        "source": "manual"
    }, headers=headers)
    assert res.status_code == 200, res.text

    db = SessionLocal()
    try:
        stored = db.query(Transaction).filter(Transaction.id == res.json()["id"]).first()
        assert isinstance(stored.amount, Decimal)
        assert stored.amount == Decimal("19.99")
    finally:
        db.close()


def test_account_balance_has_no_float_drift_across_many_transactions(client, auth_headers):
    """30 debits of 0.10 must sum to exactly 3.00 — the classic case where
    IEEE-754 float accumulation drifts (0.1 has no exact binary
    representation), which is exactly the failure mode NUMERIC(12,2) +
    Decimal exists to rule out for a balance users are trusting to be exact."""
    headers, _ = auth_headers
    account = client.post("/api/accounts", json={
        "name": "Wallet", "type": "cash", "currency": "INR", "opening_balance": 10
    }, headers=headers).json()

    for _ in range(30):
        res = client.post("/api/transactions", json={
            "amount": 0.10, "currency": "INR", "type": "debit", "category": "food",
            "merchant": "Vending", "description": "snack", "date": "2026-08-01T12:00:00",
            "source": "manual", "account_id": account["id"]
        }, headers=headers)
        assert res.status_code == 200, res.text

    updated = client.get("/api/accounts", headers=headers).json()[0]
    assert updated["balance"] == 7.0

    # Recompute independently of the API response (which round-trips through
    # the float-serializing wire format) to prove the stored figure itself,
    # not just its JSON rendering, is exact.
    db = SessionLocal()
    try:
        txns = db.query(Transaction).filter(Transaction.account_id == account["id"]).all()
        exact_balance = Decimal("10") - sum((t.amount for t in txns), Decimal("0"))
        assert exact_balance == Decimal("7.00")
    finally:
        db.close()


def test_budget_spent_amount_has_no_float_drift(client, auth_headers):
    headers, _ = auth_headers
    client.post("/api/budgets", json={"category": "food", "limit_amount": 100, "period": "monthly"}, headers=headers)

    for _ in range(10):
        res = client.post("/api/transactions", json={
            "amount": 3.33, "currency": "INR", "type": "debit", "category": "food",
            "merchant": "Cafe", "description": "coffee", "date": _in_period_date(),
            "source": "manual"
        }, headers=headers)
        assert res.status_code == 200, res.text

    budget = client.get("/api/budgets", headers=headers).json()[0]

    db = SessionLocal()
    try:
        stored_budget = db.query(Budget).filter(Budget.id == budget["id"]).first()
        assert isinstance(stored_budget.spent_amount, Decimal)
        assert stored_budget.spent_amount == Decimal("33.30")
    finally:
        db.close()


def test_amount_travels_on_the_wire_as_a_json_number_not_a_string(client, auth_headers):
    """The frontend contract stays unchanged: Decimal is exact server-side,
    but Pydantic's response serialization must keep emitting a plain JSON
    number for `amount`/`balance`/etc, not the string Pydantic v2 defaults
    to for a bare Decimal field — every existing frontend numeric consumer
    (charts, sorting, budget math, CSV) depends on this."""
    headers, _ = auth_headers
    res = client.post("/api/transactions", json={
        "amount": 19.99, "currency": "INR", "type": "debit", "category": "food",
        "merchant": "Cafe", "description": "lunch", "date": "2026-08-01T12:00:00",
        "source": "manual"
    }, headers=headers)
    assert res.status_code == 200, res.text

    raw = json.loads(res.text)
    assert isinstance(raw["amount"], float)
