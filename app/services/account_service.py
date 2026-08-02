from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.account import LIABILITY_TYPES, Account
from app.models.transaction import Transaction
from app.services.exchange_rate_service import to_home_currency


class AccountInUseError(Exception):
    """Raised when deleting an account still referenced by a transaction."""
    pass


def compute_balance(db: Session, account: Account) -> float:
    """
    For asset accounts, balance is money held: opening_balance + credits - debits.
    For credit_card accounts, balance is money owed, which moves the other way —
    a purchase (debit) increases what's owed, a payment (credit) reduces it —
    so the terms flip: opening_balance + debits - credits.
    """
    credits = db.query(func.coalesce(func.sum(Transaction.amount), 0.0)).filter(
        Transaction.account_id == account.id, Transaction.type == "credit"
    ).scalar()
    debits = db.query(func.coalesce(func.sum(Transaction.amount), 0.0)).filter(
        Transaction.account_id == account.id, Transaction.type == "debit"
    ).scalar()
    credits, debits = float(credits or 0.0), float(debits or 0.0)

    if account.type in LIABILITY_TYPES:
        return account.opening_balance + debits - credits
    return account.opening_balance + credits - debits


class AccountService:
    @staticmethod
    def list_visible(db: Session, user_id: str, include_archived: bool = False) -> list[Account]:
        query = db.query(Account).filter(Account.user_id == user_id)
        if not include_archived:
            query = query.filter(Account.is_archived.is_(False))
        return query.order_by(Account.created_at).all()

    @staticmethod
    def get_own(db: Session, user_id: str, account_id: str) -> Account | None:
        return db.query(Account).filter(Account.id == account_id, Account.user_id == user_id).first()

    @staticmethod
    def create(db: Session, user_id: str, name: str, type: str, currency: str, opening_balance: float) -> Account:
        account = Account(
            user_id=user_id, name=name.strip(), type=type,
            currency=currency, opening_balance=opening_balance
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        return account

    @staticmethod
    def update(
        db: Session, account: Account,
        name: str | None, opening_balance: float | None, is_archived: bool | None
    ) -> Account:
        if name is not None:
            account.name = name.strip()
        if opening_balance is not None:
            account.opening_balance = opening_balance
        if is_archived is not None:
            account.is_archived = is_archived
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
    def to_response(db: Session, account: Account) -> dict:
        return {
            "id": account.id,
            "name": account.name,
            "type": account.type,
            "currency": account.currency,
            "opening_balance": account.opening_balance,
            "balance": compute_balance(db, account),
            "is_archived": account.is_archived,
            "created_at": account.created_at
        }

    @staticmethod
    def net_worth(db: Session, user_id: str) -> dict:
        """
        Each account's own `balance` stays in that account's native
        currency (matches how it's displayed). The combined totals below
        are always in the home currency, so each account's balance is
        converted before folding it in — otherwise a USD credit card's
        balance would get added straight to INR bank balances.
        """
        accounts = AccountService.list_visible(db, user_id)

        total_assets = 0.0
        total_liabilities = 0.0
        items = []
        today = date.today()
        for account in accounts:
            balance = compute_balance(db, account)
            balance_home = to_home_currency(balance, account.currency, today)
            if account.type in LIABILITY_TYPES:
                total_liabilities += balance_home
            else:
                total_assets += balance_home
            items.append({"id": account.id, "name": account.name, "type": account.type, "balance": balance})

        return {
            "net_worth": total_assets - total_liabilities,
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "accounts": items
        }
