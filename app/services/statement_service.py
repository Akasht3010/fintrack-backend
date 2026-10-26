import hashlib
import re
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.transaction import Transaction
from app.services.account_service import _digits, _hint_matches
from app.services.budget_service import BudgetService
from app.services.categorizer import categorize_merchant
from app.services.statement_parser import ParsedStatement, StatementRow, describe_narration

# Alerts carry a time, statement rows only a date (and the bank may post a
# late-night payment on the next day) — so a row matches an existing
# transaction dated within a day either side.
MATCH_WINDOW = timedelta(days=1)


class StatementAccountMismatch(Exception):
    def __init__(self, statement_digits: str, account_digits: str):
        self.statement_digits = statement_digits
        self.account_digits = account_digits


def _marker(account: Account, row: StatementRow) -> str:
    # Closing balance makes two identical same-day rows (two ₹20 chais)
    # distinct, while re-uploading the same statement maps each row to the
    # same marker — the (user_id, raw_text) unique index makes it idempotent.
    key = f"{row.date.isoformat()}|{row.narration}|{row.debit}|{row.credit}|{row.closing_balance}"
    return f"stmt:{account.id}:{hashlib.sha1(key.encode()).hexdigest()[:20]}"


def _poor_merchant(name: str) -> bool:
    return not re.search(r"[A-Za-z]{2,}", name or "") or name in ("Bank transaction", "UPI payment")


def _same_ref(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    a, b = a.lstrip("0"), b.lstrip("0")
    return len(a) >= 6 and len(b) >= 6 and (a.endswith(b) or b.endswith(a))


def _belongs_to(txn: Transaction, account: Account, other_digits: list[str]) -> bool:
    """Linked to this account; or unlinked, and not quoting digits that
    belong to one of the user's other accounts (e.g. a debit card number
    the user never entered is still most likely this account's card)."""
    if txn.account_id is not None:
        return txn.account_id == account.id
    if not txn.account_hint:
        return True
    hints = txn.account_hint.split(",")
    if any(_hint_matches(h, d) for h in hints for d in _digits(account)):
        return True
    return not any(_hint_matches(h, d) for h in hints for d in other_digits)


def import_statement(db: Session, user_id: int, account: Account, statement: ParsedStatement) -> dict:
    if statement.account_last4 and account.last4 and not statement.account_last4.endswith(account.last4):
        raise StatementAccountMismatch(statement.account_last4, account.last4)

    rows = statement.rows
    start = min(r.date for r in rows)
    end = max(r.date for r in rows)
    window_start = datetime.combine(start, time.min) - MATCH_WINDOW
    window_end = datetime.combine(end, time.max) + MATCH_WINDOW

    other_digits = [
        d for other in db.query(Account).filter(Account.user_id == user_id, Account.id != account.id).all()
        for d in _digits(other)
    ]
    existing = [
        t for t in db.query(Transaction).filter(
            Transaction.user_id == user_id,
            Transaction.date >= window_start,
            Transaction.date <= window_end,
        ).all()
        if _belongs_to(t, account, other_digits)
    ]
    by_marker = {t.raw_text: t for t in existing if t.raw_text}
    matched_ids: set[int] = set()

    added: list[Transaction] = []
    matched = 0
    already = 0
    added_debits = Decimal("0")

    for row in rows:
        marker = _marker(account, row)
        if marker in by_marker:
            already += 1
            matched_ids.add(by_marker[marker].id)
            continue

        details = describe_narration(row.narration)
        reference = details.reference or row.reference
        is_debit = row.debit > 0
        amount = row.debit if is_debit else row.credit
        txn_type = "debit" if is_debit else "credit"
        row_day = datetime.combine(row.date, time(12, 0))

        candidates = [
            t for t in existing
            if t.id not in matched_ids and t.amount == amount and t.type == txn_type
            and abs(t.date - row_day) <= MATCH_WINDOW + timedelta(hours=12)
        ]
        match = next((t for t in candidates if _same_ref(t.reference, reference)), None)
        if match is None:
            # Same amount and direction within a day — prefer the closest in time,
            # but never one whose UPI reference says it's a different payment.
            plausible = [t for t in candidates if not (t.reference and reference and not _same_ref(t.reference, reference))]
            match = min(plausible, key=lambda t: abs(t.date - row_day), default=None)

        if match is not None:
            matched += 1
            matched_ids.add(match.id)
            if match.account_id is None:
                match.account_id = account.id
            if not match.reference and reference:
                match.reference = reference
            if not match.payment_method:
                match.payment_method = details.payment_method
            # The alert's payee was unreadable (a helpline number, a terminal
            # id, the generic fallback) — the statement names it properly.
            if _poor_merchant(match.merchant) and not _poor_merchant(details.merchant):
                match.merchant = details.merchant[:100]
                if match.category == "other":
                    match.category = details.category or categorize_merchant(details.merchant, row.narration)
            continue

        category = details.category or categorize_merchant(details.merchant, row.narration)
        txn = Transaction(
            user_id=user_id,
            account_id=account.id,
            amount=amount,
            currency="INR",
            type=txn_type,
            category=category,
            merchant=details.merchant[:100],
            description=row.narration[:200] or details.merchant,
            # Statement rows have no time — midday keeps them on the right
            # calendar day whatever the reader's timezone handling.
            date=row_day,
            source="statement",
            raw_text=marker,
            payment_method=details.payment_method,
            reference=reference,
            balance_after=row.closing_balance,
            is_recurring=False,
        )
        try:
            # Savepoint per row: a concurrent import of the same statement
            # hitting the unique index loses just this row, not the batch.
            with db.begin_nested():
                db.add(txn)
        except IntegrityError:
            already += 1
            continue
        added.append(txn)
        if is_debit and category != "transfer":
            added_debits += amount

    # The statement's last closing balance is the bank's own figure as of
    # the end of that day — anchor on it unless something newer exists.
    last_row = rows[-1]
    balance_set = False
    if last_row.closing_balance is not None:
        at = datetime.combine(last_row.date, time(23, 59, 59))
        if account.reported_balance_at is None or at >= account.reported_balance_at:
            account.reported_balance = last_row.closing_balance
            account.reported_balance_at = at
            account.reported_balance_source = "statement"
            balance_set = True

    db.commit()
    BudgetService.sync_for_categories(db, user_id, {t.category for t in added})

    # In the app for this account and period, but not on the statement —
    # most likely a duplicate or a payment linked to the wrong account.
    period_start = datetime.combine(start, time.min)
    period_end = datetime.combine(end, time.max)
    not_in_statement = [
        t for t in existing
        if t.id not in matched_ids and t.account_id == account.id and t.source != "statement"
        and period_start <= t.date <= period_end
    ]

    return {
        "bank": statement.bank,
        "account_last4": statement.account_last4,
        "period_start": start,
        "period_end": end,
        "rows": len(rows),
        "matched": matched,
        "already_imported": already,
        "added": len(added),
        "added_debit_total": added_debits,
        "closing_balance": last_row.closing_balance,
        "balance_updated": balance_set,
        "not_in_statement": [
            {"id": t.id, "date": t.date, "merchant": t.merchant, "amount": t.amount, "type": t.type}
            for t in sorted(not_in_statement, key=lambda t: t.date)
        ],
    }
