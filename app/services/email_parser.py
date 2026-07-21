import re
from typing import Optional, TypedDict

AMOUNT_PATTERN = re.compile(r"(?:INR|Rs\.?|₹)\s?([\d,]+(?:\.\d{1,2})?)", re.IGNORECASE)

DEBIT_WORDS = re.compile(r"\b(debited|spent|paid|purchase|withdrawn|debit)\b", re.IGNORECASE)
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

MERCHANT_PATTERNS = [
    re.compile(r"\bat\s+([A-Za-z0-9 &.'_-]{2,40}?)(?:\s+(?:on|dated|via)\b|[.,\n]|$)", re.IGNORECASE),
    re.compile(r"\btowards\s+([A-Za-z0-9 &.'_-]{2,40}?)(?:\s+(?:on|dated|via)\b|[.,\n]|$)", re.IGNORECASE),
    re.compile(r"\bto\s+([A-Za-z0-9 &.'_-]{2,40}?)(?:\s+(?:on|dated|via)\b|[.,\n]|$)", re.IGNORECASE),
]


class ParsedEmailTransaction(TypedDict):
    amount: float
    type: str  # "debit" | "credit"
    merchant: str


def parse_bank_email(subject: str, body: str, snippet: str, sender: str) -> Optional[ParsedEmailTransaction]:
    """
    Best-effort extraction of a transaction from a bank alert email.
    Bank email formats vary a lot; this covers common patterns
    (Rs./INR/₹ amount, debited/credited wording, "at <merchant>") and
    returns None if it can't confidently find an amount, or if the email
    is reporting a failed/declined payment attempt (no money moved).
    """
    text = f"{subject}\n{body}\n{snippet}"

    if FAILURE_WORDS.search(text):
        return None

    amount_match = AMOUNT_PATTERN.search(text)
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

    merchant = None
    for pattern in MERCHANT_PATTERNS:
        match = pattern.search(text)
        if match:
            candidate = match.group(1).strip()
            if candidate:
                merchant = candidate
                break

    if not merchant:
        sender_name = sender.split("<")[0].strip().strip('"')
        merchant = sender_name or "Bank transaction"

    return {
        "amount": amount,
        "type": txn_type,
        "merchant": merchant[:100]
    }
