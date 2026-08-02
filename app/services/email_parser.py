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

# UPI debit alerts name the payee twice: an opaque VPA handle, and (almost
# always) the registered name behind it in parentheses right after — that
# name is the actual "where did this money go"; the VPA alone is not
# human-readable (e.g. "VPA paytm-51955531@ptys (Dominos Pizza)").
VPA_NAMED_PATTERN = re.compile(r"VPA\s+[\w.\-]+@[\w.\-]+\s*\(([^)]{2,60})\)", re.IGNORECASE)

# No name given alongside the VPA — fall back to its local part (before the
# @), which is still the payee's own handle rather than the sending bank.
VPA_BARE_PATTERN = re.compile(r"VPA\s+([\w.\-]+)@[\w.\-]+", re.IGNORECASE)

# NEFT/IMPS/RTGS/fund-transfer confirmations lay the payee out as a
# "Beneficiary Name" field rather than in a sentence — \s* around the label
# already spans a line break, so this matches whether the value sits on the
# same line or the next one.
BENEFICIARY_PATTERN = re.compile(r"Beneficiary\s*Name\s*[:\-]?\s*([^\n\r]{2,60})", re.IGNORECASE)

MERCHANT_PATTERNS = [
    re.compile(r"\bat\s+([A-Za-z0-9 &.'_-]{2,40}?)(?:\s+(?:on|dated|via)\b|[.,\n]|$)", re.IGNORECASE),
    re.compile(r"\btowards\s+([A-Za-z0-9 &.'_-]{2,40}?)(?:\s+(?:on|dated|via)\b|[.,\n]|$)", re.IGNORECASE),
    re.compile(r"\bto\s+([A-Za-z0-9 &.'_-]{2,40}?)(?:\s+(?:on|dated|via)\b|[.,\n]|$)", re.IGNORECASE),
]

TRANSFER_MODE_PATTERN = re.compile(r"\b(NEFT|IMPS|RTGS)\b", re.IGNORECASE)
FUND_TRANSFER_PATTERN = re.compile(r"\bfund\s+transfer\b", re.IGNORECASE)
UPI_MODE_PATTERN = re.compile(r"\b(UPI|VPA)\b", re.IGNORECASE)


class ParsedEmailTransaction(TypedDict):
    amount: float
    type: str  # "debit" | "credit"
    merchant: str
    description: str


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
        # Some banks render the whole details table as one line with big
        # gaps between fields rather than one field per line — cut at the
        # first such gap so we don't swallow the next label too.
        candidate = re.split(r"\s{2,}", match.group(1).strip())[0].strip()
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

    merchant, confident = _extract_merchant(text)
    if not merchant:
        # Never show the alerting bank as if it were the payee — that's
        # actively misleading ("spent at HDFC Bank InstaAlerts").
        merchant = "Bank transaction"

    if confident:
        mode = _transfer_mode(text)
        verb = "Received from" if is_credit else "Paid to"
        description = f"{verb} {merchant}"
        if mode:
            description += f" via {mode}"
    else:
        description = subject.strip() or merchant

    return {
        "amount": amount,
        "type": txn_type,
        "merchant": merchant[:100],
        "description": description[:200]
    }
