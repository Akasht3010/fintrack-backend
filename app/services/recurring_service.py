from collections import defaultdict
from datetime import timedelta
from statistics import mean
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.transaction import Transaction

# (cadence, target interval in days, tolerance in days)
CADENCE_WINDOWS = [
    ("weekly", 7, 3),
    ("monthly", 30, 7),
    ("yearly", 365, 25),
]

MONTHLY_EQUIVALENT = {
    "weekly": 4.348,
    "monthly": 1.0,
    "yearly": 1 / 12
}

# How much a merchant's transaction amounts are allowed to vary and still
# count as "the same bill" — subscriptions occasionally tick up in price.
AMOUNT_SPREAD_TOLERANCE = 0.2

def _cadence_for_interval(avg_interval_days: float) -> Optional[str]:
    for cadence, target, tolerance in CADENCE_WINDOWS:
        if abs(avg_interval_days - target) <= tolerance:
            return cadence
    return None

def detect_recurring(db: Session, user_id: str) -> List[dict]:
    """Group the user's debit transactions by merchant and flag groups whose
    spacing and amount are consistent enough to be a recurring bill."""
    transactions = (
        db.query(Transaction)
        .filter(Transaction.user_id == user_id, Transaction.type == "debit")
        .order_by(Transaction.date)
        .all()
    )

    groups: dict[str, list[Transaction]] = defaultdict(list)
    for t in transactions:
        groups[t.merchant.strip().lower()].append(t)

    results = []
    for txns in groups.values():
        if len(txns) < 2:
            continue

        txns = sorted(txns, key=lambda t: t.date)
        intervals = [
            (txns[i].date - txns[i - 1].date).days
            for i in range(1, len(txns))
            if (txns[i].date - txns[i - 1].date).days > 0
        ]
        if not intervals:
            continue

        avg_interval = mean(intervals)
        cadence = _cadence_for_interval(avg_interval)
        if not cadence:
            continue

        amounts = [t.amount for t in txns]
        avg_amount = mean(amounts)
        if avg_amount <= 0:
            continue
        amount_spread = (max(amounts) - min(amounts)) / avg_amount
        if amount_spread > AMOUNT_SPREAD_TOLERANCE:
            continue

        last = txns[-1]
        results.append({
            "merchant": last.merchant,
            "category": last.category,
            "average_amount": round(avg_amount, 2),
            "cadence": cadence,
            "occurrences": len(txns),
            "last_date": last.date,
            "next_due_date": last.date + timedelta(days=round(avg_interval))
        })

    results.sort(key=lambda r: r["next_due_date"])
    return results
