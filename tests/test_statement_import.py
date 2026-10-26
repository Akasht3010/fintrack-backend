from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.statement_parser import StatementFormatError, describe_narration, parse_hdfc_statement

FIXTURES = Path(__file__).parent / "fixtures"
TXT = (FIXTURES / "hdfc_statement.txt").read_bytes()
XLS = (FIXTURES / "hdfc_statement.xls").read_bytes()


# --- parser -----------------------------------------------------------------

def test_parses_hdfc_delimited_statement():
    st = parse_hdfc_statement(TXT, "Acct_Statement.txt")
    assert st.account_last4 == "1234"
    assert len(st.rows) == 9
    swiggy = st.rows[1]
    assert swiggy.debit == Decimal("649.00") and swiggy.credit == 0
    assert swiggy.reference == "427512345678"
    assert swiggy.closing_balance == Decimal("119351.00")
    assert st.rows[-1].credit == Decimal("206.00")


def test_parses_hdfc_xls_statement_and_joins_wrapped_narration():
    st = parse_hdfc_statement(XLS, "Acct_Statement.xls")
    assert st.account_last4 == "1234"
    assert [r.debit for r in st.rows] == [Decimal("649.00"), Decimal("1499.00")]
    assert st.rows[1].narration == "POS 416021XXXXXX4455 AMAZON PAY INDIA"


def test_rejects_pdf_and_unrelated_files():
    with pytest.raises(StatementFormatError):
        parse_hdfc_statement(b"%PDF-1.7 ...", "statement.pdf")
    with pytest.raises(StatementFormatError):
        parse_hdfc_statement(b"name,age\nbob,3\n", "people.csv")


@pytest.mark.parametrize("narration, merchant, method, category", [
    ("UPI-SWIGGY-SWIGGY@ICICI-ICIC0DC0099-427512345678-PAYMENT FROM PHONE", "Swiggy", "upi", None),
    ("POS 416021XXXXXX4455 AMAZON PAY INDIA", "Amazon Pay India", "card", None),
    ("ATW-416021XXXXXX4455-S1ACNM04-MUMBAI", "ATM withdrawal", "atm", None),
    ("ACH D- TP ACH ICICIPRULIFE-1234567890", "Icicipurulife".replace("puru", "pru"), "autopay", None),
    ("CC 000416021XXXXXX9876 AUTOPAY SI-TAD", "Credit card bill", "autopay", "transfer"),
    ("NEFT CR-ICIC0000001-ACME TECHNOLOGIES PVT LTD-SALARY OCT 2026-X", "Acme Technologies Pvt Ltd", "netbanking", "salary"),
    ("UPI-CRED CLUB-CRED.CLUB@AXISB-UTIB0000114-528900000001-CC BILL", "Cred Club", "upi", "transfer"),
])
def test_narration_details(narration, merchant, method, category):
    d = describe_narration(narration)
    assert (d.merchant, d.payment_method, d.category) == (merchant, method, category)


# --- import -----------------------------------------------------------------

def _bank(client, headers, last4="1234"):
    res = client.post("/api/accounts", json={"name": "HDFC", "type": "bank", "institution": "HDFC", "last4": last4}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def _upload(client, headers, account_id, content=TXT, name="statement.txt"):
    return client.post(
        "/api/statements/import",
        data={"account_id": str(account_id)},
        files={"file": (name, content, "text/plain")},
        headers=headers,
    )


def _sms(body, when):
    return {"address": "VM-HDFCBK", "body": body, "date": int(when.timestamp() * 1000)}


def test_import_matches_alerts_adds_missing_rows_and_sets_balance(client, auth_headers):
    headers, _ = auth_headers
    acct = _bank(client, headers)
    # Two of the statement's payments already arrived as alerts.
    client.post("/api/sms/sync", json={"messages": [
        _sms("Rs.649.00 debited from A/c XX1234 UPI Ref 427512345678", datetime(2026, 10, 2, 13, 5)),
        _sms("Rs.1499.00 spent on Card XX4455 at AMAZON", datetime(2026, 10, 5, 19, 40)),
        # In the app but not on the statement — reported back.
        _sms("Rs.75.00 debited from A/c XX1234 UPI Ref 999999999999", datetime(2026, 10, 9, 9, 0)),
    ]}, headers=headers)

    res = _upload(client, headers, acct["id"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["rows"] == 9
    # ₹649 by UPI ref; ₹1499 by amount + day — its card digits (••4455)
    # aren't on any account, so it's taken to be this account's debit card.
    assert body["matched"] == 2
    assert body["added"] == 7
    assert body["balance_updated"] is True
    assert Decimal(body["closing_balance"]) == Decimal("98518.00")
    assert [(i["merchant"], i["amount"]) for i in body["not_in_statement"]] == [("Bank transaction", "75.00")]

    accounts = {a["id"]: a for a in client.get("/api/accounts", headers=headers).json()}
    assert Decimal(accounts[acct["id"]]["balance"]) == Decimal("98518.00")
    assert accounts[acct["id"]]["balance_source"] == "statement"

    # Two ₹20 chai payments the same day stay two transactions.
    chai = client.get(f"/api/transactions?account_id={acct['id']}&q=chai", headers=headers).json()
    assert chai["total"] == 2


def test_alert_for_another_accounts_card_is_not_claimed(client, auth_headers):
    headers, _ = auth_headers
    acct = _bank(client, headers)
    client.post("/api/accounts", json={"name": "Axis", "type": "bank", "last4": "7777", "card_last4": "4455"}, headers=headers)
    client.post("/api/sms/sync", json={"messages": [
        _sms("Rs.1499.00 spent on Card XX4455 at AMAZON", datetime(2026, 10, 5, 19, 40)),
    ]}, headers=headers)
    body = _upload(client, headers, acct["id"]).json()
    assert body["matched"] == 0 and body["added"] == 9


def test_alert_matched_by_debit_card_digits_and_wrong_account_reported(client, auth_headers):
    headers, _ = auth_headers
    acct = client.post("/api/accounts", json={
        "name": "HDFC", "type": "bank", "last4": "1234", "card_last4": "4455"
    }, headers=headers).json()
    client.post("/api/sms/sync", json={"messages": [
        _sms("Rs.1499.00 spent on Card XX4455 at AMAZON", datetime(2026, 10, 5, 19, 40)),
        _sms("Rs.75.00 debited from A/c XX1234 UPI Ref 999999999999", datetime(2026, 10, 9, 9, 0)),
    ]}, headers=headers)

    body = _upload(client, headers, acct["id"]).json()
    assert body["matched"] == 1
    assert body["added"] == 8
    assert [(i["merchant"], i["amount"]) for i in body["not_in_statement"]] == [("Bank transaction", "75.00")]


def test_reuploading_is_idempotent(client, auth_headers):
    headers, _ = auth_headers
    acct = _bank(client, headers)
    first = _upload(client, headers, acct["id"]).json()
    second = _upload(client, headers, acct["id"]).json()
    assert first["added"] == 9
    # 649 + 20 + 20 + 1499 + 2000 + 2500 — not the ₹15,000 card bill payment (a transfer)
    assert Decimal(first["added_debit_total"]) == Decimal("6688.00")
    assert second["added"] == 0 and second["already_imported"] == 9
    assert client.get(f"/api/transactions?account_id={acct['id']}", headers=headers).json()["total"] == 9


def test_later_alert_for_a_statement_row_is_not_duplicated(client, auth_headers):
    headers, _ = auth_headers
    acct = _bank(client, headers)
    _upload(client, headers, acct["id"])
    res = client.post("/api/sms/sync", json={"messages": [
        _sms("Rs.1499.00 debited from A/c XX1234 at AMAZON", datetime(2026, 10, 5, 19, 40)),
    ]}, headers=headers).json()
    assert res["imported"] == 0


def test_card_bill_payment_and_salary_are_not_spend_or_income_noise(client, auth_headers):
    headers, _ = auth_headers
    acct = _bank(client, headers)
    _upload(client, headers, acct["id"])
    txns = client.get(f"/api/transactions?account_id={acct['id']}&limit=50", headers=headers).json()["transactions"]
    by_amount = {t["amount"]: t for t in txns}
    assert by_amount["15000.00"]["category"] == "transfer"
    assert by_amount["85000.00"]["category"] == "salary"
    assert by_amount["2000.00"]["payment_method"] == "atm"


def test_statement_for_another_account_is_rejected(client, auth_headers):
    headers, _ = auth_headers
    acct = _bank(client, headers, last4="9999")
    res = _upload(client, headers, acct["id"])
    assert res.status_code == 400
    assert "1234" in res.json()["detail"]


def test_bad_file_is_a_422_not_a_500(client, auth_headers):
    headers, _ = auth_headers
    acct = _bank(client, headers)
    res = _upload(client, headers, acct["id"], content=b"%PDF-1.4 binary", name="s.pdf")
    assert res.status_code == 422
