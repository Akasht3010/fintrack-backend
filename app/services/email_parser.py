import re
from decimal import Decimal, InvalidOperation
from typing import Optional, TypedDict

# Currency before amount ("INR 500", "INR: 500.00", "Rs.500", "₹500") is the
# common case; some templates put the currency after instead ("500.00 INR"),
# so both orders are tried, in that order, at match time.
AMOUNT_PATTERNS = [
    re.compile(r"(?:INR|Rs\.?|₹)\s*[:.]?\s*([\d,]+(?:\.\d{1,2})?)", re.IGNORECASE),
    re.compile(r"([\d,]+(?:\.\d{1,2})?)\s*(?:INR|Rs\.?|₹)", re.IGNORECASE),
    # Last resort, no currency marker at all — SBI's UPI SMS reads
    # "A/C X1234 debited by 20.0 on 26Oct26 trf to ...".
    re.compile(r"\b(?:debited|credited)\s+(?:by|with|for)\s+([\d,]+(?:\.\d{1,2})?)\b", re.IGNORECASE),
]

_MONEY = r"(?:INR|Rs\.?|₹)\s*[:.]?\s*([\d,]+(?:\.\d{1,2})?)"

# The account's balance after this transaction ("Avl Bal Rs 12,345.67",
# "Available balance: INR 500", "Bal: Rs.20"). It's the figure that keeps the
# app's balance in step with the bank's, and it must never be mistaken for
# the transaction amount — some templates put it first.
BALANCE_PATTERN = re.compile(
    r"\b(?:(?:avl|avbl|avail|available|a/c|acct|account|clear|closing|updated|net)\.?\s*)?"
    r"bal(?:ance)?\b\.?\s*(?:is\s*)?[:\-]?\s*" + _MONEY,
    re.IGNORECASE
)

# A credit card's remaining credit limit — also not the transaction amount,
# and not a balance either (what's owed is limit minus this).
LIMIT_PATTERN = re.compile(
    r"\b(?:avl|avbl|avail|available)\.?\s*(?:credit\s*)?(?:limit|lmt)\b\.?\s*(?:is\s*)?[:\-]?\s*" + _MONEY,
    re.IGNORECASE
)

# The masked account / card number the alert is about: "A/c XX1234",
# "account ending 5115", "AC X1234", "Acct XX123" (ICICI shows 3 digits),
# "Credit Card XX1234", "card ending with 1234". Only the trailing digits
# are ever shown, and only those are kept.
_MASK = r"(?:\s*(?:no\.?|number))?\s*(?:ending\s*(?:with|in)?)?\s*[:\-]?\s*[xX*•.]*\s*(\d{3,6})\b"
ACCOUNT_NUMBER_PATTERN = re.compile(r"\b(?:a/c|acct|account|ac)\b\.?" + _MASK, re.IGNORECASE)
CARD_NUMBER_PATTERN = re.compile(r"\bcard\b" + _MASK, re.IGNORECASE)

# UPI reference / UTR / RRN — the one identifier the bank SMS, the bank
# email and the UPI app all quote for the same payment, so the strongest
# possible duplicate signal.
REFERENCE_PATTERN = re.compile(
    r"\b(?:UPI\s*(?:transaction\s*)?(?:ref(?:erence)?\.?\s*(?:no\.?|number|id)?|id)|"
    r"UTR(?:\s*no\.?)?|RRN|Ref(?:erence)?\.?\s*(?:no\.?|number|id)?|Refno|UPI)"
    r"\s*(?:is\s*)?[:.\-]?\s*((?=[A-Za-z0-9]*\d)[A-Za-z0-9]{6,22})\b",
    re.IGNORECASE
)

# How the money moved — checked in this order, first match wins. UPI beats
# card on purpose: UPI on a RuPay credit card is still a UPI payment, which
# is what a UPI app's own "spent this month" counts.
PAYMENT_METHOD_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("autopay", re.compile(
        r"\b(NACH|ECS|e-?mandate|auto-?pay|auto-?debit|standing\s+instruction|SI\s+txn)\b", re.IGNORECASE)),
    ("atm", re.compile(r"\b(ATM|cash\s+withdrawal|withdrawn)\b", re.IGNORECASE)),
    ("upi", re.compile(r"\b(UPI|VPA)\b|@(?:ok\w+|ybl|ibl|axl|paytm|ptys|upi)\b", re.IGNORECASE)),
    ("card", re.compile(r"\b(?:debit|credit)\s*card\b|\bcard\b|\bPOS\b", re.IGNORECASE)),
    ("netbanking", re.compile(
        r"\b(NEFT|IMPS|RTGS|fund\s+transfer|net\s*banking|internet\s+banking)\b", re.IGNORECASE)),
]

# Paying a credit card bill. The purchases on the card are already counted
# as spend when they happen; counting the bill payment from the bank account
# as well would count every card purchase twice — so both sides of it (the
# bank debit and the card's "payment received") are tagged as a transfer.
CARD_BILL_PAYMENT_PATTERN = re.compile(
    r"\bcredit\s*card\s*(?:bill\s*)?payment\b|"
    r"\bCC\s*(?:bill\s*)?payment\b|"
    r"\bpayment\b.{0,60}?\b(?:received|credited)\b.{0,40}?\b(?:towards|to|on|for)\s+(?:your\s+)?.{0,30}?\bcard\b|"
    r"\btowards\s+(?:your\s+)?(?:[\w&]+\s+){0,3}credit\s*card\b",
    re.IGNORECASE | re.DOTALL
)
CARD_BILL_PAYEES = re.compile(r"^\s*(?:cred|cred\s*club|cheq|credit\s*card\s*bill)\s*$", re.IGNORECASE)

DEBIT_WORDS = re.compile(
    r"\b(debited|spent|paid|purchase|purchased|withdrawn|debit|used|charged|billed|transaction\s+of)\b",
    re.IGNORECASE
)
CREDIT_WORDS = re.compile(r"\b(credited|received|deposited|credit|refund)\b", re.IGNORECASE)

# Emails announcing a payment attempt that didn't go through — no money
# actually moved, so these must never be recorded as a transaction, even
# though they usually mention an amount.
FAILURE_WORDS = re.compile(
    r"\b(failed|failure|declined|decline|unsuccessful|denied|"
    r"not\s+(?:been\s+)?processed|could\s+not\s+be\s+processed|"
    r"insufficient\s+(?:balance|funds)|payment\s+error|transaction\s+error|"
    r"has\s+not\s+gone\s+through|did\s+not\s+go\s+through)\b",
    re.IGNORECASE
)

# Statements and credit-card bills quote an amount (running balance, total
# due, minimum due) but no money moved on receipt of the email — recording
# them creates a phantom transaction, often for a large amount.
STATEMENT_BILL_WORDS = re.compile(
    r"\b("
    r"e-?statement|mini\s*statement|monthly\s+statement|account\s+statement|"
    r"statement\s+(?:is\s+)?(?:ready|generated|available|attached)|"
    r"total\s+amount\s+due|minimum\s+amount\s+due|min(?:imum)?\s+amt\s+due|"
    r"amount\s+due|bill\s+(?:generated|amount|date)|payment\s+due|due\s+date|"
    r"outstanding\s+(?:amount|balance)"
    r")\b",
    re.IGNORECASE
)

# Advance notices for e-mandates / autopay / standing instructions ("Rs.89
# will be debited on 28-10-26 for the E-mandate set up for GOOGLE PLAY") —
# RBI makes banks send these a day ahead. Nothing has moved yet, and the
# real debit gets its own alert later, so recording the notice counts the
# payment twice.
UPCOMING_DEBIT_WORDS = re.compile(
    r"\b(will\s+be\s+(?:debited|charged|deducted|auto-?debited)|to\s+be\s+debited|"
    r"pre-?debit|upcoming\s+(?:debit|payment|e-?mandate)|is\s+scheduled|scheduled\s+to\s+be)\b",
    re.IGNORECASE
)

# UPI debit alerts name the payee twice: an opaque VPA handle, and (almost
# always) the registered name behind it in parentheses right after — that
# name is the actual "where did this money go"; the VPA alone is not
# human-readable (e.g. "VPA paytm-51955531@ptys (Dominos Pizza)").
VPA_NAMED_PATTERN = re.compile(r"VPA\s+[\w.\-]+@[\w.\-]+\s*\(([^)]{2,60})\)", re.IGNORECASE)

# HDFC's UPI emails put the name after the VPA with no brackets:
# "to VPA paytmqr5abc@ptys MOHAMMAD SHAFIQUE SI on 25-10-26".
VPA_NAME_AFTER_PATTERN = re.compile(
    r"VPA\s+[\w.\-]+@[\w.\-]+\s+(?!on\b|dated\b|via\b)([A-Za-z][A-Za-z0-9 &.'_-]{1,58}?)(?=\s+on\b|\s*[.,;]\s|\s*$|\n)",
    re.IGNORECASE
)

# No name given alongside the VPA — fall back to its local part (before the
# @), which is still the payee's own handle rather than the sending bank.
VPA_BARE_PATTERN = re.compile(r"VPA\s+([\w.\-]+)@[\w.\-]+", re.IGNORECASE)

# NEFT/IMPS/RTGS/fund-transfer confirmations lay the payee out as a
# "Beneficiary Name" field among several others — Gmail's HTML-to-text
# conversion doesn't reliably leave a newline (or even a double space)
# between adjacent fields, so a real email can read
# "Beneficiary Name: AKASH KOTAK BANK Beneficiary A/c No.: XX5115" all on
# one line with single spaces throughout. Bound the capture with the known
# field labels that follow it in these templates rather than trusting
# whitespace, or it swallows the next label's text too.
_BENEFICIARY_BOUNDARY = r"(?=\s*(?:Beneficiary|Bank\s*IFSC|A/c|UTR|Amount|Date|Transaction)\b|[\n\r]|$)"
BENEFICIARY_PATTERN = re.compile(
    r"Beneficiary\s*Name\s*[:\-]?\s*([A-Za-z0-9 .&'_-]{2,60}?)" + _BENEFICIARY_BOUNDARY,
    re.IGNORECASE
)

# The trailing boundary treats "." as a clause end only when it's followed
# by whitespace/end-of-string, not mid-token — otherwise merchant names like
# "AMAZON.IN" get truncated to "AMAZON" at the domain dot.
_MERCHANT_BOUNDARY = r"(?:\s+(?:on|dated|via|using|ref(?:no)?|upi|utr|avl|bal|if)\b|[.,;](?=\s|$)|\n|$)"

MERCHANT_PATTERNS = [
    re.compile(r"\bat\s+([A-Za-z0-9 &.'_-]{2,40}?)" + _MERCHANT_BOUNDARY, re.IGNORECASE),
    re.compile(r"\btowards\s+([A-Za-z0-9 &.'_-]{2,40}?)" + _MERCHANT_BOUNDARY, re.IGNORECASE),
    re.compile(r"\bto\s+([A-Za-z0-9 &.'_-]{2,40}?)" + _MERCHANT_BOUNDARY, re.IGNORECASE),
]

TRANSFER_MODE_PATTERN = re.compile(r"\b(NEFT|IMPS|RTGS)\b", re.IGNORECASE)
FUND_TRANSFER_PATTERN = re.compile(r"\bfund\s+transfer\b", re.IGNORECASE)
UPI_MODE_PATTERN = re.compile(r"\b(UPI|VPA)\b", re.IGNORECASE)


class ParsedEmailTransaction(TypedDict):
    amount: Decimal
    type: str  # "debit" | "credit"
    merchant: str
    description: str
    category: Optional[str]  # set to "transfer" for bank-to-bank transfers; else None
    payment_method: str  # upi | card | netbanking | atm | autopay | other
    account_hints: list[str]  # trailing digits of the account/card, account first
    balance_after: Optional[Decimal]  # the alert's "Avl Bal", if it quotes one
    reference: Optional[str]  # UPI ref / UTR / RRN, if it quotes one


def _to_decimal(raw: str) -> Optional[Decimal]:
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None


def _find_amount(text: str) -> Optional[Decimal]:
    """The first amount in the text that isn't a balance or a credit limit."""
    excluded = [m.span() for p in (BALANCE_PATTERN, LIMIT_PATTERN) for m in p.finditer(text)]
    for pattern in AMOUNT_PATTERNS:
        for match in pattern.finditer(text):
            start = match.start(1)
            if any(lo <= start < hi for lo, hi in excluded):
                continue
            return _to_decimal(match.group(1))
    return None


def _account_hints(text: str) -> list[str]:
    hints: list[str] = []
    for pattern in (ACCOUNT_NUMBER_PATTERN, CARD_NUMBER_PATTERN):
        for match in pattern.finditer(text):
            digits = match.group(1)[-4:]
            if digits not in hints:
                hints.append(digits)
    return hints


def _payment_method(text: str) -> str:
    for method, pattern in PAYMENT_METHOD_PATTERNS:
        if pattern.search(text):
            return method
    return "other"


def _looks_numeric(candidate: str) -> bool:
    return not re.search(r"[A-Za-z]{2,}", candidate)


def _extract_merchant(text: str) -> tuple[Optional[str], bool]:
    """
    Best-effort payee extraction, most reliable pattern first.
    Returns (merchant, is_high_confidence) — high confidence means we found
    a real payee (not just the sending bank), so it's worth building a
    description around it rather than falling back to the raw subject.
    """
    match = VPA_NAMED_PATTERN.search(text)
    if match:
        return match.group(1).strip(), True

    match = VPA_NAME_AFTER_PATTERN.search(text)
    if match:
        return match.group(1).strip(), True

    match = BENEFICIARY_PATTERN.search(text)
    if match:
        candidate = match.group(1).strip()
        if candidate:
            return candidate, True

    for pattern in MERCHANT_PATTERNS:
        for match in pattern.finditer(text):
            candidate = match.group(1).strip()
            # A bare number is a helpline ("SMS BLOCK UPI to 7308080808") or
            # a terminal id ("At 627711073250"), never the payee.
            if candidate and not _looks_numeric(candidate):
                return candidate, True

    match = VPA_BARE_PATTERN.search(text)
    if match:
        handle = re.sub(r"[.\-_]+", " ", match.group(1)).strip()
        if handle:
            return handle.title(), True

    return None, False


def _transfer_mode(text: str) -> Optional[str]:
    match = TRANSFER_MODE_PATTERN.search(text)
    if match:
        return match.group(1).upper()
    if FUND_TRANSFER_PATTERN.search(text):
        return "Fund Transfer"
    if UPI_MODE_PATTERN.search(text):
        return "UPI"
    return None


def parse_bank_email(subject: str, body: str, snippet: str, sender: str) -> Optional[ParsedEmailTransaction]:
    """
    Best-effort extraction of a transaction from a bank alert email.
    Bank email formats vary a lot; this covers common patterns
    (Rs./INR/₹ amount, debited/credited wording, "at <merchant>", UPI VPA
    payee names, NEFT/IMPS/RTGS "Beneficiary Name" fields) and returns None
    if it can't confidently find an amount, or if the email is reporting a
    failed/declined payment attempt (no money moved).
    """
    text = f"{subject}\n{body}\n{snippet}"

    if FAILURE_WORDS.search(text):
        return None

    if STATEMENT_BILL_WORDS.search(text):
        return None

    if UPCOMING_DEBIT_WORDS.search(text):
        return None

    # Decimal(str), not float(str) — a bank alert's amount must round-trip
    # exactly into the same NUMERIC(12,2) a manual entry would produce,
    # not the nearest binary float approximation.
    amount = _find_amount(text)
    if amount is None or amount <= 0:
        return None

    balance_match = BALANCE_PATTERN.search(text)
    balance_after = _to_decimal(balance_match.group(1)) if balance_match else None
    reference_match = REFERENCE_PATTERN.search(text)

    is_credit = bool(CREDIT_WORDS.search(text)) and not DEBIT_WORDS.search(text)
    txn_type = "credit" if is_credit else "debit"

    merchant, confident = _extract_merchant(text)
    if not merchant and _payment_method(text) == "atm":
        merchant, confident = "ATM withdrawal", False
    if not merchant:
        # Never show the alerting bank as if it were the payee — that's
        # actively misleading ("spent at HDFC Bank InstaAlerts").
        merchant = "Bank transaction"

    category = None
    if confident:
        mode = _transfer_mode(text)
        verb = "Received from" if is_credit else "Paid to"
        description = f"{verb} {merchant}"
        if mode:
            description += f" via {mode}"
        # NEFT / IMPS / RTGS / "fund transfer" are account-to-account money
        # movement, not spend or income — most often between the user's own
        # accounts. Tag them so aggregations can leave them out (a transfer
        # nets to zero across the two accounts). UPI is left uncategorized:
        # a UPI payment to a person is just as likely a real expense.
        if mode in ("NEFT", "IMPS", "RTGS", "Fund Transfer"):
            category = "transfer"
    else:
        description = subject.strip() or merchant

    if CARD_BILL_PAYMENT_PATTERN.search(text) or CARD_BILL_PAYEES.match(merchant):
        category = "transfer"

    return {
        "amount": amount,
        "type": txn_type,
        "merchant": merchant[:100],
        "description": description[:200],
        "category": category,
        "payment_method": _payment_method(text),
        "account_hints": _account_hints(text),
        "balance_after": balance_after,
        "reference": reference_match.group(1) if reference_match else None,
    }
