from app.utils.timezone import now_ist


def _date(day_hour=12):
    return now_ist().replace(hour=day_hour, minute=0, second=0, microsecond=0).isoformat()


def _post(client, headers, **overrides):
    payload = {
        "amount": 100.0, "type": "debit", "category": "food",
        "merchant": "Cafe", "description": "x", "date": _date(), "source": "manual",
    }
    payload.update(overrides)
    r = client.post("/api/transactions", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_transfers_are_excluded_from_spend_and_income_totals(client, auth_headers):
    headers, _ = auth_headers

    _post(client, headers, amount=700.0, type="debit", category="food")
    _post(client, headers, amount=5000.0, type="credit", category="salary")
    # An account-to-account move: debit on one side, credit on the other.
    _post(client, headers, amount=18000.0, type="debit", category="transfer", merchant="Own Kotak")
    _post(client, headers, amount=18000.0, type="credit", category="transfer", merchant="Own HDFC")

    data = client.get("/api/insights", params={"months": 1}, headers=headers).json()

    assert data["monthly_totals"][-1]["total"] == 700.0          # not 18700
    assert data["monthly_income_totals"][-1]["total"] == 5000.0   # not 23000
    assert [c["category"] for c in data["category_breakdown"]] == ["food"]
    assert all(m["merchant"] != "Own Kotak" for m in data["top_merchants"])
