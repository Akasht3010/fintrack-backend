import re
from typing import Optional, TypedDict

# Currency before amount ("INR 500", "INR: 500.00", "Rs.500", "₹500") is the
# common case; some templates put the currency after instead ("500.00 INR"),
# so both orders are tried, in that order, at match time.
AMOUNT_PATTERNS = [
    re.compile(r"(?:INR|Rs\.?|₹)\s*[:.]?\s*([\d,]+(?:\.\d{1,2})?)", re.IGNORECASE),
    re.compile(r"([\d,]+(?:\.\d{1,2})?)\s*(?:INR|Rs\.?|₹)", re.IGNORECASE),
]

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

# UPI debit alerts name the payee twice: an opaque VPA handle, and (almost
# always) the registered name behind it in parentheses right after — that
# name is the actual "where did this money go"; the VPA alone is not
# human-readable (e.g. "VPA paytm-51955531@ptys (Dominos Pizza)").
VPA_NAMED_PATTERN = re.compile(r"VPA\s+[\w.\-]+@[\w.\-]+\s*\(([^)]{2,60})\)", re.IGNORECASE)

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
_MERCHANT_BOUNDARY = r"(?:\s+(?:on|dated|via|using)\b|[.,](?=\s|$)|\n|$)"

MERCHANT_PATTERNS = [
    re.compile(r"\bat\s+([A-Za-z0-9 &.'_-]{2,40}?)" + _MERCHANT_BOUNDARY, re.IGNORECASE),
    re.compile(r"\btowards\s+([A-Za-z0-9 &.'_-]{2,40}?)" + _MERCHANT_BOUNDARY, re.IGNORECASE),
    re.compile(r"\bto\s+([A-Za-z0-9 &.'_-]{2,40}?)" + _MERCHANT_BOUNDARY, re.IGNORECASE),
]

TRANSFER_MODE_PATTERN = re.compile(r"\b(NEFT|IMPS|RTGS)\b", re.IGNORECASE)
FUND_TRANSFER_PATTERN = re.compile(r"\bfund\s+transfer\b", re.IGNORECASE)
UPI_MODE_PATTERN = re.compile(r"\b(UPI|VPA)\b", re.IGNORECASE)


class ParsedEmailTransaction(TypedDict):
    amount: float
    type: str  # "debit" | "credit"
    merchant: str
    description: str
    category: Optional[str]  # set to "transfer" for bank-to-bank transfers; else None


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

    match = BENEFICIARY_PATTERN.search(text)
    if match:
        candidate = match.group(1).strip()
        if candidate:
            return candidate, True

    for pattern in MERCHANT_PATTERNS:
        match = pattern.search(text)
        if match:
            candidate = match.group(1).strip()
            if candidate:
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

    amount_match = None
    for pattern in AMOUNT_PATTERNS:
        amount_match = pattern.search(text)
        if amount_match:
            break
    if not amount_match:
        return None

    try:
        amount = float(amount_match.group(1).replace(",", ""))
    except ValueError:
        return None

    if amount <= 0:
        return None

    is_credit = bool(CREDIT_WORDS.search(text)) and not DEBIT_WORDS.search(text)
    txn_type = "credit" if is_credit else "debit"

    merchant, confident = _extract_merchant(text)
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

    return {
        "amount": amount,
        "type": txn_type,
        "merchant": merchant[:100],
        "description": description[:200],
        "category": category,
    }
