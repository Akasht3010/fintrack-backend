from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.transaction import Transaction

# One real purchase often produces several alerts minutes apart — the bank
# SMS, the bank email, the card-network alert, the UPI-app receipt — each a
# distinct message. Anything with the same amount *and direction* within
# this window (from any source) is collapsed to a single row.
DEDUP_WINDOW = timedelta(minutes=10)


class ImportDeduper:
    """Shared by the Gmail and SMS sync endpoints. Direction matters: a
    debit and a same-amount credit minutes apart (a purchase and its
    refund/reversal) are two real transactions, and used to collapse into
    one because only the amount was compared."""

    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id
        self._seen: list[tuple[Decimal, str, datetime]] = []

    def is_duplicate(self, amount: Decimal, type: str, when: datetime) -> bool:
        window = DEDUP_WINDOW.total_seconds()
        if any(
            a == amount and t == type and abs((seen - when).total_seconds()) <= window
            for a, t, seen in self._seen
        ):
            return True
        return self.db.query(Transaction.id).filter(
            Transaction.user_id == self.user_id,
            Transaction.amount == amount,
            Transaction.type == type,
            Transaction.date >= when - DEDUP_WINDOW,
            Transaction.date <= when + DEDUP_WINDOW,
        ).first() is not None

    def record(self, amount: Decimal, type: str, when: datetime) -> None:
        self._seen.append((amount, type, when))
