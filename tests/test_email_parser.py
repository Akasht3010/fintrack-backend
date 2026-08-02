from app.services.email_parser import parse_bank_email


def test_upi_debit_with_named_payee_extracts_merchant_not_sender():
    # Real HDFC InstaAlert format: payee name is in "(...)" right after the VPA.
    result = parse_bank_email(
        subject="You have done a UPI txn. Check details!",
        body=(
            "Dear Customer,\n\nGreetings from HDFC Bank!\n\n"
            "Rs.181.60 is debited from your account ending 5115 towards VPA "
            "paytm-51955531@ptys (Dominos Pizza) on 02-08-26.\n\n"
            "UPI transaction reference no.: 127271995271."
        ),
        snippet="Dear Customer, Greetings from HDFC Bank! Rs.181.60 is debited...",
        sender="HDFC Bank InstaAlerts <alerts@hdfcbank.bank.in>",
    )
    assert result["amount"] == 181.60
    assert result["type"] == "debit"
    assert result["merchant"] == "Dominos Pizza"
    assert result["description"] == "Paid to Dominos Pizza via UPI"


def test_upi_debit_to_a_person_extracts_payee_name():
    result = parse_bank_email(
        subject="You have done a UPI txn. Check details!",
        body=(
            "Rs.1900.00 is debited from your account ending 5115 towards VPA "
            "jagrutijethva19@okhdfcbank (Mrs Jagruti Bhikhu Jethva) on 01-08-26.\n\n"
            "UPI transaction reference no.: 127190711052."
        ),
        snippet="",
        sender="HDFC Bank InstaAlerts <alerts@hdfcbank.bank.in>",
    )
    assert result["merchant"] == "Mrs Jagruti Bhikhu Jethva"
    assert result["description"] == "Paid to Mrs Jagruti Bhikhu Jethva via UPI"


def test_upi_debit_without_payee_name_falls_back_to_vpa_handle():
    result = parse_bank_email(
        subject="You have done a UPI txn. Check details!",
        body="Rs.250.00 is debited from your account ending 5115 towards VPA merchant-store@ybl on 02-08-26.",
        snippet="",
        sender="HDFC Bank InstaAlerts <alerts@hdfcbank.bank.in>",
    )
    assert result["merchant"] == "Merchant Store"
    assert result["type"] == "debit"


def test_neft_extracts_beneficiary_name_field():
    # Real SBI NEFT format: fields are tab-separated, one per line.
    result = parse_bank_email(
        subject="NEFT Transaction",
        body=(
            "Dear Customer,\n\nThank you for banking with State Bank of India.\n\n"
            "The details of the NEFT transaction originated by you are given below.\n\n"
            "A/c Debited:\tXX0845\nDate:\t02/08/2026\nUTR No.:\tSBIN126214695208\n"
            "Beneficiary Name:\tAKASH KOTAK BANK\nBeneficiary A/c No.:\tXX5115\n"
            "Bank IFSC:\tKKBK0000877\nAmount Remitted:\tINR 18,000.00"
        ),
        snippet="",
        sender="neftinfo.itps <neftinfo.itps@alerts.sbi.bank.in>",
    )
    assert result["amount"] == 18000.0
    assert result["type"] == "debit"
    assert result["merchant"] == "AKASH KOTAK BANK"
    assert result["description"] == "Paid to AKASH KOTAK BANK via NEFT"


def test_fund_transfer_extracts_beneficiary_and_tags_mode():
    # Real YONO SBI format: no NEFT/IMPS/RTGS keyword, only "Fund Transfer" prose.
    result = parse_bank_email(
        subject="Transaction success",
        body=(
            "Dear AKASH HEMAL KUMAR THAKKAR\n\n"
            "Thank you for using YONO SBI for Fund Transfer\n\n"
            "The transaction details are as follows:\n\n"
            "Description\tDetails\nTransaction Status\tSuccessful\nAmount\tRs.5,000.00\n"
            "Transaction Number\tSBIN126214695929\nDate of Transaction\t02.08.26\n"
            "Debit account\tx0845\nBeneficiary Name\tAKASH THAKKAR"
        ),
        snippet="",
        sender="yonobysbi@alerts.sbi.bank.in",
    )
    assert result["merchant"] == "AKASH THAKKAR"
    assert result["description"] == "Paid to AKASH THAKKAR via Fund Transfer"


def test_card_purchase_still_matched_by_at_pattern():
    result = parse_bank_email(
        subject="Transaction Alert",
        body="You have spent INR 799.00 at AMAZON.IN using your card ending 4321 on 03-Aug-26.",
        snippet="",
        sender="ICICI Bank <alerts@icicibank.com>",
    )
    assert result["merchant"] == "AMAZON.IN"
    assert result["description"] == "Paid to AMAZON.IN"


def test_credit_email_uses_received_verb():
    result = parse_bank_email(
        subject="Credit Alert",
        body="Rs.2,500.00 has been credited to your account towards Refund from FLIPKART on 03-Aug-26.",
        snippet="",
        sender="Axis Bank <alerts@axisbank.com>",
    )
    assert result["type"] == "credit"
    assert result["merchant"] == "Refund from FLIPKART"
    assert result["description"].startswith("Received from")


def test_no_recognizable_payee_falls_back_to_generic_merchant_not_sender_name():
    result = parse_bank_email(
        subject="Account Alert",
        body="Rs.100.00 has been debited from your account. Avl Bal Rs.5000.00",
        snippet="",
        sender="Bank Alerts <noreply@somebank.com>",
    )
    assert result["merchant"] == "Bank transaction"
    # Low-confidence merchant: description should stay the original subject,
    # not a synthesized "Paid to Bank transaction" sentence.
    assert result["description"] == "Account Alert"


def test_failed_payment_is_not_recorded():
    result = parse_bank_email(
        subject="Payment Failed",
        body="Your payment of Rs.500.00 at AMAZON.IN has failed due to insufficient balance.",
        snippet="",
        sender="HDFC Bank <alerts@hdfcbank.bank.in>",
    )
    assert result is None


def test_email_with_no_amount_is_not_recorded():
    result = parse_bank_email(
        subject="Statement Ready",
        body="Your monthly account statement is now available for download.",
        snippet="",
        sender="HDFC Bank <alerts@hdfcbank.bank.in>",
    )
    assert result is None
