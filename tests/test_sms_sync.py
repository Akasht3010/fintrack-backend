from datetime import datetime

BASE_MS = int(datetime(2026, 9, 5, 12, 0, 0).timestamp() * 1000)


def _msg(amount, minutes_offset, address="VM-HDFCBK"):
    return {
        "address": address,
        "body": f"Rs.{amount:.2f} is debited from your account ending 1234 towards VPA store@ybl on 05-09-26.",
        "date": BASE_MS + minutes_offset * 60_000,
    }


def test_sms_sync_imports_a_parseable_debit(client, auth_headers):
    headers, _ = auth_headers
    res = client.post("/api/sms/sync", json={"messages": [_msg(500, 0)]}, headers=headers)
    assert res.status_code == 200, res.text
    assert res.json() == {"imported": 1, "skipped_duplicate": 0, "skipped_unparsed": 0}


def test_same_amount_within_the_window_is_one_transaction(client, auth_headers):
    headers, _ = auth_headers
    # Same purchase, two alerts 3 minutes apart (e.g. bank SMS + a resend).
    res = client.post("/api/sms/sync", json={
        "messages": [_msg(500, 0, address="VM-HDFCBK"), _msg(500, 3, address="AD-HDFCBK")]
    }, headers=headers)
    assert res.json()["imported"] == 1
    assert res.json()["skipped_duplicate"] == 1


def test_same_amount_outside_the_window_is_two_transactions(client, auth_headers):
    headers, _ = auth_headers
    res = client.post("/api/sms/sync", json={
        "messages": [_msg(500, 0), _msg(500, 45, address="VK-HDFCBK")]
    }, headers=headers)
    assert res.json()["imported"] == 2


def test_a_second_sync_does_not_re_import_the_same_message(client, auth_headers):
    headers, _ = auth_headers
    client.post("/api/sms/sync", json={"messages": [_msg(500, 0)]}, headers=headers)
    res = client.post("/api/sms/sync", json={"messages": [_msg(500, 0)]}, headers=headers)
    assert res.json()["imported"] == 0
    assert res.json()["skipped_duplicate"] == 1


def test_credit_card_bill_sms_is_not_imported(client, auth_headers):
    headers, _ = auth_headers
    res = client.post("/api/sms/sync", json={"messages": [{
        "address": "VM-HDFCBK",
        "body": "Total Amount Due Rs.42500.00 on your card ending 4321. Payment Due Date 20-Sep-26.",
        "date": BASE_MS,
    }]}, headers=headers)
    assert res.json()["imported"] == 0
    assert res.json()["skipped_unparsed"] == 1


def test_sms_sync_rejects_more_messages_than_one_sync_can_send(client, auth_headers):
    headers, _ = auth_headers
    res = client.post("/api/sms/sync", json={"messages": [_msg(500, i) for i in range(501)]}, headers=headers)
    assert res.status_code == 422


def test_sms_sync_rejects_oversized_fields(client, auth_headers):
    headers, _ = auth_headers
    for bad in ({"body": "x" * 2001}, {"address": "A" * 65}, {"date": 10**20}, {"date": -1}):
        res = client.post("/api/sms/sync", json={"messages": [{**_msg(500, 0), **bad}]}, headers=headers)
        assert res.status_code == 422, (bad, res.text)


def test_a_debit_and_a_same_amount_refund_minutes_apart_are_both_imported(client, auth_headers):
    """Dedup used to compare amount only, so a purchase and its reversal
    collapsed into one row — dropping a real credit."""
    headers, _ = auth_headers
    refund = {
        "address": "VM-HDFCBK",
        "body": "Rs.500.00 has been credited to your account ending 1234 towards Refund from FLIPKART on 05-09-26.",
        "date": BASE_MS + 4 * 60_000,
    }
    res = client.post("/api/sms/sync", json={"messages": [_msg(500, 0), refund]}, headers=headers)
    assert res.json()["imported"] == 2, res.json()
    types = sorted(t["type"] for t in client.get("/api/transactions", headers=headers).json()["transactions"])
    assert types == ["credit", "debit"]


def test_same_direction_duplicate_across_syncs_still_collapses(client, auth_headers):
    """The DB-side check (not just within one sync) also matches on type."""
    headers, _ = auth_headers
    client.post("/api/sms/sync", json={"messages": [_msg(500, 0, address="VM-HDFCBK")]}, headers=headers)
    res = client.post("/api/sms/sync", json={"messages": [_msg(500, 2, address="AD-HDFCBK")]}, headers=headers)
    assert res.json()["imported"] == 0
