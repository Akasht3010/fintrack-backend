from datetime import datetime
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.account import LIABILITY_TYPES, Account
from app.models.transaction import Transaction


class AccountInUseError(Exception):
    """Raised when deleting an account still referenced by a transaction."""
    pass


def _sums(db: Session, accounts: list[Account]) -> dict[int, dict[str, Decimal]]:
    """Credit/debit totals per account, counting only what came after each
    account's anchor (if it has one). One GROUP BY query for the unanchored
    accounts; one per anchored account — there are only ever a handful."""
    sums = {account.id: {"credit": Decimal("0"), "debit": Decimal("0")} for account in accounts}

    def add(rows):
        for account_id, transaction_type, total in rows:
            if account_id in sums and transaction_type in sums[account_id]:
                sums[account_id][transaction_type] = total or Decimal("0")

    plain = [a.id for a in accounts if a.reported_balance is None]
    if plain:
        add(
            db.query(Transaction.account_id, Transaction.type, func.sum(Transaction.amount))
            .filter(Transaction.account_id.in_(plain))
            .group_by(Transaction.account_id, Transaction.type)
            .all()
        )
    for account in accounts:
        if account.reported_balance is None:
            continue
        add(
            db.query(Transaction.account_id, Transaction.type, func.sum(Transaction.amount))
            .filter(Transaction.account_id == account.id, Transaction.date > account.reported_balance_at)
            .group_by(Transaction.account_id, Transaction.type)
            .all()
        )
    return sums


def compute_balances(db: Session, accounts: list[Account]) -> dict[int, Decimal]:
    """
    Without an anchor: opening_balance + every linked transaction.
    With one (the bank's own figure, from an alert or typed in by the user):
    that figure + only the transactions after it. The bank's number already
    includes everything up to that moment — including anything the app never
    imported — so it's what keeps the balance matching the bank.
    """
    if not accounts:
        return {}
    sums = _sums(db, accounts)
    result = {}
    for account in accounts:
        base = account.reported_balance if account.reported_balance is not None else account.opening_balance
        credits, debits = sums[account.id]["credit"], sums[account.id]["debit"]
        if account.type in LIABILITY_TYPES:
            result[account.id] = base + debits - credits
        else:
            result[account.id] = base + credits - debits
    return result


def compute_balance(db: Session, account: Account) -> Decimal:
    return compute_balances(db, [account])[account.id]


def _digits(account: Account) -> list[str]:
    return [d for d in (account.last4, account.card_last4) if d]


def _hint_matches(hint: str, digits: str) -> bool:
    # Banks print 3–4 trailing digits (ICICI shows "XX123"), so a shorter
    # hint matches on the tail of the stored digits.
    return len(hint) >= 3 and digits.endswith(hint)


class AccountMatcher:
    """Maps the account/card digits a bank alert quotes to one of the user's
    accounts. Ambiguous digits (two accounts ending the same) match nothing
    rather than guessing."""

    def __init__(self, db: Session, user_id: int):
        self.accounts = (
            db.query(Account)
            .filter(Account.user_id == user_id, Account.is_archived.is_(False))
            .all()
        )

    def match(self, hints: Iterable[str]) -> Optional[Account]:
        for hint in hints:
            found = [a for a in self.accounts if any(_hint_matches(hint, d) for d in _digits(a))]
            if len(found) == 1:
                return found[0]
        return None


def apply_reported_balance(account: Account, balance: Decimal, at: datetime, source: str) -> None:
    """Move the anchor forward only — an older alert arriving late (a
    backlog sync) must not replace a newer figure."""
    if account.type in LIABILITY_TYPES:
        return  # a card alert's "available" figure is credit limit, not what's owed
    if account.reported_balance_at is None or at >= account.reported_balance_at:
        account.reported_balance = balance
        account.reported_balance_at = at
        account.reported_balance_source = source


def link_imported_transactions(db: Session, account: Account) -> int:
    """Claim unlinked imports whose alert quoted this account's digits —
    for when the account is added (or its digits filled in) after the
    transactions were already synced. Also picks up the newest "Avl Bal"
    among them as the anchor."""
    digits = _digits(account)
    if not digits:
        return 0
    candidates = (
        db.query(Transaction)
        .filter(
            Transaction.user_id == account.user_id,
            Transaction.account_id.is_(None),
            Transaction.account_hint.isnot(None),
        )
        .all()
    )
    others = [
        a for a in db.query(Account).filter(
            Account.user_id == account.user_id, Account.id != account.id, Account.is_archived.is_(False)
        ).all()
    ]
    linked = 0
    for txn in candidates:
        hints = txn.account_hint.split(",")
        mine = any(_hint_matches(h, d) for h in hints for d in digits)
        theirs = any(_hint_matches(h, d) for h in hints for a in others for d in _digits(a))
        if mine and not theirs:
            txn.account_id = account.id
            linked += 1
            if txn.balance_after is not None:
                apply_reported_balance(account, txn.balance_after, txn.date, "alert")
    db.commit()
    return linked


class AccountService:
    @staticmethod
    def list_visible(db: Session, user_id: int, include_archived: bool = False) -> list[Account]:
        query = db.query(Account).filter(Account.user_id == user_id)
        if not include_archived:
            query = query.filter(Account.is_archived.is_(False))
        return query.order_by(Account.created_at).all()

    @staticmethod
    def get_own(db: Session, user_id: int, account_id: int) -> Account | None:
        return db.query(Account).filter(Account.id == account_id, Account.user_id == user_id).first()

    @staticmethod
    def create(
        db: Session, user_id: int, name: str, type: str, currency: str, opening_balance: Decimal,
        institution: str | None = None, last4: str | None = None, card_last4: str | None = None
    ) -> Account:
        account = Account(
            user_id=user_id, name=name.strip(), type=type,
            currency="INR", opening_balance=opening_balance,
            institution=(institution or "").strip() or None, last4=last4 or None, card_last4=card_last4 or None
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        link_imported_transactions(db, account)
        db.refresh(account)
        return account

    @staticmethod
    def update(
        db: Session, account: Account,
        name: str | None, opening_balance: Decimal | None, is_archived: bool | None,
        fields_set: set[str] = frozenset(), institution: str | None = None,
        last4: str | None = None, card_last4: str | None = None
    ) -> Account:
        if name is not None:
            account.name = name.strip()
        # Explicitly sent (even as null/"") means change it — clearing is allowed.
        if "institution" in fields_set:
            account.institution = (institution or "").strip() or None
        if "last4" in fields_set:
            account.last4 = last4 or None
        if "card_last4" in fields_set:
            account.card_last4 = card_last4 or None
        if opening_balance is not None:
            account.opening_balance = opening_balance
        if is_archived is not None:
            account.is_archived = is_archived
        db.commit()
        if fields_set & {"last4", "card_last4", "is_archived"}:
            link_imported_transactions(db, account)
        db.refresh(account)
        return account

    @staticmethod
    def set_balance(db: Session, account: Account, balance: Decimal, at: datetime) -> Account:
        """The user typed in the balance their bank / UPI app shows right
        now. Unlike an alert's figure this always wins — it's the user
        correcting the record — except against a newer alert."""
        if account.reported_balance_at is None or at >= account.reported_balance_at:
            account.reported_balance = balance
            account.reported_balance_at = at
            account.reported_balance_source = "manual"
        db.commit()
        db.refresh(account)
        return account

    @staticmethod
    def delete(db: Session, account: Account) -> None:
        in_use = db.query(Transaction).filter(Transaction.account_id == account.id).first()
        if in_use:
            raise AccountInUseError()
        db.delete(account)
        db.commit()

    @staticmethod
    def to_response(db: Session, account: Account, balance: Decimal | None = None) -> dict:
        return {
            "id": account.id,
            "name": account.name,
            "type": account.type,
            "currency": account.currency,
            "opening_balance": account.opening_balance,
            "balance": balance if balance is not None else compute_balance(db, account),
            "institution": account.institution,
            "last4": account.last4,
            "card_last4": account.card_last4,
            "balance_source": account.reported_balance_source,
            "balance_as_of": account.reported_balance_at,
            "is_archived": account.is_archived,
            "created_at": account.created_at
        }

    @staticmethod
    def net_worth(db: Session, user_id: int) -> dict:
        """Asset balances minus liability balances (all INR)."""
        accounts = AccountService.list_visible(db, user_id)
        balances = compute_balances(db, accounts)

        total_assets = Decimal("0")
        total_liabilities = Decimal("0")
        items = []
        for account in accounts:
            balance = balances[account.id]
            if account.type in LIABILITY_TYPES:
                total_liabilities += balance
            else:
                total_assets += balance
            items.append({"id": account.id, "name": account.name, "type": account.type, "balance": balance})

        return {
            "net_worth": total_assets - total_liabilities,
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "accounts": items
        }
