from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy.orm import Session

from app.models.transaction import Transaction
from app.services.account_service import AccountMatcher, apply_reported_balance
from app.services.email_parser import ParsedEmailTransaction

# One real purchase often produces several alerts minutes apart — the bank
# SMS, the bank email, the card-network alert, the UPI-app receipt — each a
# distinct message. Anything with the same amount *and direction* within
# this window (from any source) is collapsed to a single row — unless the
# alerts prove they're different payments (see is_duplicate).
DEDUP_WINDOW = timedelta(minutes=10)


def _hints(raw: Optional[str]) -> set[str]:
    return set(raw.split(",")) if raw else set()


class ImportDeduper:
    """Shared by the Gmail and SMS sync endpoints. Direction matters: a
    debit and a same-amount credit minutes apart (a purchase and its
    refund/reversal) are two real transactions, and used to collapse into
    one because only the amount was compared."""

    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id
        self._seen: list[tuple[Decimal, str, datetime, Optional[str], set[str]]] = []

    @staticmethod
    def _same_payment(ref_a, hints_a, ref_b, hints_b) -> bool:
        # Two ₹20 UPI payments a few minutes apart are two payments: different
        # UPI references, or different accounts, prove it. With nothing to
        # tell them apart, assume it's the same payment alerted twice.
        if ref_a and ref_b:
            return ref_a == ref_b
        if hints_a and hints_b and not (hints_a & hints_b):
            return False
        return True

    def is_duplicate(
        self, amount: Decimal, type: str, when: datetime,
        reference: Optional[str] = None, hints: Sequence[str] = ()
    ) -> bool:
        hints_set = set(hints)
        if reference:
            if any(ref == reference for _, _, _, ref, _ in self._seen):
                return True
            same_ref = self.db.query(Transaction.id).filter(
                Transaction.user_id == self.user_id,
                Transaction.reference == reference,
                Transaction.amount == amount,
            ).first()
            if same_ref is not None:
                return True

        window = DEDUP_WINDOW.total_seconds()
        for a, t, seen, ref, seen_hints in self._seen:
            if a == amount and t == type and abs((seen - when).total_seconds()) <= window:
                if self._same_payment(reference, hints_set, ref, seen_hints):
                    return True

        nearby = self.db.query(Transaction.reference, Transaction.account_hint).filter(
            Transaction.user_id == self.user_id,
            Transaction.amount == amount,
            Transaction.type == type,
            Transaction.date >= when - DEDUP_WINDOW,
            Transaction.date <= when + DEDUP_WINDOW,
        ).all()
        return any(self._same_payment(reference, hints_set, ref, _hints(h)) for ref, h in nearby)

    def record(
        self, amount: Decimal, type: str, when: datetime,
        reference: Optional[str] = None, hints: Sequence[str] = ()
    ) -> None:
        self._seen.append((amount, type, when, reference, set(hints)))


def apply_alert_details(txn: Transaction, parsed: ParsedEmailTransaction, matcher: AccountMatcher) -> None:
    """Copies what the alert says about *where* the money moved onto the
    row, links it to the matching account, and lets the alert's "Avl Bal"
    move that account's balance anchor. Used for new imports and to
    backfill rows imported before these fields existed."""
    txn.payment_method = parsed["payment_method"]
    txn.account_hint = ",".join(parsed["account_hints"]) or None
    txn.reference = parsed["reference"]
    txn.balance_after = parsed["balance_after"]
    if parsed.get("category") == "transfer":
        txn.category = "transfer"

    if txn.account_id is None:
        account = matcher.match(parsed["account_hints"])
        if account is not None:
            txn.account_id = account.id
    if txn.account_id is not None and parsed["balance_after"] is not None:
        account = next((a for a in matcher.accounts if a.id == txn.account_id), None)
        if account is not None:
            apply_reported_balance(account, parsed["balance_after"], txn.date, "alert")


def note_reported_balance(parsed: ParsedEmailTransaction, when: datetime, matcher: AccountMatcher) -> None:
    """For an alert skipped as a duplicate: the copy that was kept may not
    have quoted the balance (HDFC's emails don't, its SMS do), so take it
    from this one."""
    if parsed["balance_after"] is None:
        return
    account = matcher.match(parsed["account_hints"])
    if account is not None:
        apply_reported_balance(account, parsed["balance_after"], when, "alert")
