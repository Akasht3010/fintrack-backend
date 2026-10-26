from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock
import base64

from app.services.email_parser import parse_bank_email
from app.services.gmail_service import GmailService

BASE_MS = int(datetime(2026, 9, 5, 12, 0, 0).timestamp() * 1000)


def _sms(body, minutes_offset=0, address="VM-HDFCBK"):
    return {"address": address, "body": body, "date": BASE_MS + minutes_offset * 60_000}


def _parse(body):
    return parse_bank_email(subject="", body=body, snippet="", sender="")


# --- parser -----------------------------------------------------------------

def test_balance_is_read_and_never_taken_as_the_amount():
    # Balance quoted *before* the amount — the amount must still be the debit.
    parsed = _parse("Avl Bal Rs 12,345.67. Rs.250.00 debited from A/c XX1234 on 05-09-26 UPI Ref 512345678901")
    assert parsed["amount"] == Decimal("250.00")
    assert parsed["balance_after"] == Decimal("12345.67")
    assert parsed["account_hints"] == ["1234"]
    assert parsed["reference"] == "512345678901"
    assert parsed["payment_method"] == "upi"


def test_sbi_upi_sms_without_a_currency_marker_is_parsed():
    parsed = _parse(
        "Dear UPI user A/C X4321 debited by 20.0 on date 05Sep26 trf to CHAI POINT Refno 524812345678. "
        "If not u? call 1800111109. -SBI"
    )
    assert parsed is not None
    assert parsed["amount"] == Decimal("20.0")
    assert parsed["type"] == "debit"
    assert parsed["account_hints"] == ["4321"]
    assert parsed["reference"] == "524812345678"


def test_credit_card_spend_quotes_the_card_digits_and_ignores_the_available_limit():
    parsed = _parse(
        "Rs.1,499.00 spent on HDFC Bank Card x9876 at AMAZON on 2026-09-05:12:01:02. "
        "Avl Limit: Rs 85,000.00"
    )
    assert parsed["amount"] == Decimal("1499.00")
    assert parsed["account_hints"] == ["9876"]
    assert parsed["payment_method"] == "card"
    assert parsed["balance_after"] is None


def test_icici_three_digit_account_hint():
    parsed = _parse("ICICI Bank Acct XX123 debited for Rs 250.00 on 05-Sep-26; Swiggy credited. UPI:524811112222.")
    assert parsed["account_hints"] == ["123"]
    assert parsed["type"] == "debit"
    assert parsed["reference"] == "524811112222"


def test_payment_methods():
    assert _parse("Rs.2000 withdrawn at ATM from A/c XX1234")["payment_method"] == "atm"
    assert _parse("Rs.499 debited from A/c XX1234 towards NACH mandate NETFLIX")["payment_method"] == "autopay"
    assert _parse("Rs.5000 debited from A/c XX1234 via IMPS to RAHUL")["payment_method"] == "netbanking"


def test_credit_card_bill_payment_is_a_transfer_on_both_sides():
    bank_side = _parse("Rs.15,000.00 debited from A/c XX1234 towards your HDFC credit card payment")
    card_side = _parse(
        "Payment of Rs 15,000.00 has been received towards your ICICI Bank Credit Card XX9876. Thank you."
    )
    via_cred = _parse("Rs.15000.00 is debited from your account ending 1234 towards VPA cred.club@axisb (CRED)")
    assert bank_side["category"] == "transfer"
    assert card_side["category"] == "transfer"
    assert via_cred["category"] == "transfer"


# --- sync: linking, balance anchor, dedup -----------------------------------

def _account(client, headers, **fields):
    body = {"name": "HDFC Savings", "type": "bank", "opening_balance": 0, **fields}
    res = client.post("/api/accounts", json=body, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def _accounts(client, headers):
    return {a["id"]: a for a in client.get("/api/accounts", headers=headers).json()}


def test_import_links_to_the_account_and_takes_the_banks_balance(client, auth_headers):
    headers, _ = auth_headers
    hdfc = _account(client, headers, last4="1234", institution="HDFC")
    other = _account(client, headers, name="SBI", last4="4321")

    res = client.post("/api/sms/sync", json={"messages": [
        _sms("Rs.250.00 debited from A/c XX1234 on 05-09-26 UPI Ref 512345678901. Avl Bal Rs 9,750.00", 0),
    ]}, headers=headers)
    assert res.json()["imported"] == 1

    txn = client.get("/api/transactions", headers=headers).json()["transactions"][0]
    assert txn["account_id"] == hdfc["id"]
    assert txn["payment_method"] == "upi"

    accounts = _accounts(client, headers)
    assert Decimal(accounts[hdfc["id"]]["balance"]) == Decimal("9750.00")
    assert accounts[hdfc["id"]]["balance_source"] == "alert"
    assert Decimal(accounts[other["id"]]["balance"]) == Decimal("0")


def test_transactions_after_the_anchor_move_the_balance_older_alerts_do_not(client, auth_headers):
    headers, _ = auth_headers
    hdfc = _account(client, headers, last4="1234")
    client.post("/api/sms/sync", json={"messages": [
        _sms("Rs.100.00 debited from A/c XX1234 Ref 500000000001. Avl Bal Rs 1,000.00", 0),
    ]}, headers=headers)
    # A later alert without a balance, then a backlog alert from earlier.
    client.post("/api/sms/sync", json={"messages": [
        _sms("Rs.50.00 debited from A/c XX1234 Ref 500000000002", 30),
        _sms("Rs.70.00 debited from A/c XX1234 Ref 500000000003. Avl Bal Rs 1,100.00", -30),
    ]}, headers=headers)
    assert Decimal(_accounts(client, headers)[hdfc["id"]]["balance"]) == Decimal("950.00")


def test_manual_balance_reconcile(client, auth_headers):
    headers, _ = auth_headers
    acct = _account(client, headers, last4="1234", opening_balance=500)
    res = client.post(f"/api/accounts/{acct['id']}/balance", json={"balance": 4200.5}, headers=headers)
    assert res.status_code == 200, res.text
    assert Decimal(res.json()["balance"]) == Decimal("4200.50")
    assert res.json()["balance_source"] == "manual"


def test_account_added_after_sync_claims_matching_imports(client, auth_headers):
    headers, _ = auth_headers
    client.post("/api/sms/sync", json={"messages": [
        _sms("Rs.300.00 debited from A/c XX5555 Ref 500000000010. Avl Bal Rs 2,000.00", 0),
        _sms("Rs.40.00 debited from A/c XX6666 Ref 500000000011", 1),
    ]}, headers=headers)

    acct = _account(client, headers, last4="5555")
    assert Decimal(acct["balance"]) == Decimal("2000.00")
    linked = client.get(f"/api/transactions?account_id={acct['id']}", headers=headers).json()
    assert [t["amount"] for t in linked["transactions"]] == ["300.00"]
    unlinked = client.get("/api/transactions?account_id=0", headers=headers).json()
    assert unlinked["total"] == 1


def test_two_same_amount_upi_payments_with_different_refs_are_both_kept(client, auth_headers):
    headers, _ = auth_headers
    res = client.post("/api/sms/sync", json={"messages": [
        _sms("Rs.20.00 debited from A/c XX1234 UPI Ref 500000000021", 0),
        _sms("Rs.20.00 debited from A/c XX1234 UPI Ref 500000000022", 3),
    ]}, headers=headers)
    assert res.json()["imported"] == 2


def test_same_ref_from_email_and_sms_is_one_transaction(client, auth_headers):
    headers, _ = auth_headers
    res = client.post("/api/sms/sync", json={"messages": [
        _sms("Rs.20.00 debited from A/c XX1234 UPI Ref 500000000031", 0),
        _sms("Your a/c XX1234 is debited for INR 20.00. UPI Ref No 500000000031.", 45, address="AX-HDFCBK"),
    ]}, headers=headers)
    assert res.json()["imported"] == 1
    assert res.json()["skipped_duplicate"] == 1


def test_duplicate_alert_still_contributes_its_balance(client, auth_headers):
    headers, _ = auth_headers
    acct = _account(client, headers, last4="1234")
    client.post("/api/sms/sync", json={"messages": [
        _sms("Rs.20.00 debited from A/c XX1234 UPI Ref 500000000041", 0),
        _sms("Rs.20.00 debited from A/c XX1234 UPI Ref 500000000041. Avl Bal Rs 780.00", 1),
    ]}, headers=headers)
    assert Decimal(_accounts(client, headers)[acct["id"]]["balance"]) == Decimal("780.00")


def test_insights_split_spend_by_account_and_method(client, auth_headers):
    headers, _ = auth_headers
    now = datetime.now()
    now_ms = int(now.timestamp() * 1000)
    acct = _account(client, headers, last4="1234")
    client.post("/api/sms/sync", json={"messages": [
        {"address": "HDFC", "body": "Rs.100.00 debited from A/c XX1234 UPI Ref 500000000051", "date": now_ms},
        {"address": "HDFC", "body": "Rs.400.00 spent on Card XX9999 at AMAZON", "date": now_ms - 60_000 * 30},
    ]}, headers=headers)

    body = client.get("/api/insights?months=1", headers=headers).json()
    by_account = {a["account_id"]: a["total"] for a in body["account_breakdown"]}
    assert by_account == {acct["id"]: 100.0, None: 400.0}
    by_method = {m["payment_method"]: m["total"] for m in body["payment_method_breakdown"]}
    assert by_method == {"upi": 100.0, "card": 400.0}

    upi_only = client.get("/api/insights?months=1&payment_method=upi", headers=headers).json()
    assert upi_only["monthly_totals"][-1]["total"] == 100.0


# --- gmail ------------------------------------------------------------------

def _b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode()


def test_html_only_and_nested_bodies_are_read():
    gmail = GmailService()
    html_only = {"payload": {"mimeType": "text/html", "body": {"data": _b64("<p>Rs.500&nbsp;debited from A/c <b>XX1234</b></p>")}}}
    nested = {"payload": {"mimeType": "multipart/mixed", "parts": [
        {"mimeType": "multipart/alternative", "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64("Rs.75 debited")}},
            {"mimeType": "text/html", "body": {"data": _b64("<b>ignored</b>")}},
        ]},
    ]}}
    assert gmail.get_email_body(html_only) == "Rs.500 debited from A/c XX1234"
    assert gmail.get_email_body(nested) == "Rs.75 debited"


def test_gmail_fetch_follows_pages_and_skips_known_ids():
    gmail = GmailService()
    service = MagicMock()
    pages = [
        {"messages": [{"id": "a"}, {"id": "b"}], "nextPageToken": "p2"},
        {"messages": [{"id": "c"}]},
    ]
    service.users().messages().list().execute.side_effect = pages
    gmail.get_gmail_service = lambda token: service
    gmail.get_email_details = lambda svc, message_id: {"id": message_id}

    emails = gmail.fetch_emails("token", query="q", max_results=100, skip_ids={"b"})
    assert [e["id"] for e in emails] == ["a", "c"]


def test_merchant_stops_before_the_reference_number():
    parsed = _parse("Dear UPI user A/C X7788 debited by 120.0 on date 26Oct26 trf to RAPIDO Refno 600000000104. If not u?")
    assert parsed["merchant"] == "RAPIDO"


def test_atm_withdrawal_is_named_as_such():
    assert _parse("Rs.2000.00 withdrawn at ATM from A/c XX1234. Avl Bal Rs 100.00")["merchant"] == "ATM withdrawal"
