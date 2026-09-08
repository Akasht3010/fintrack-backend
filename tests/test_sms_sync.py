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
