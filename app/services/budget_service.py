from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
import calendar

from app.models.budget import Budget
from app.models.transaction import Transaction
from app.services.exchange_rate_service import to_home_currency
from app.utils.timezone import now_ist


class DuplicateBudgetError(Exception):
    """Raised when a budget for the same category + period is already active."""
    pass


def current_period_dates(period: str, now: datetime) -> tuple[datetime, datetime]:
    """Compute the start/end of the current week or month, containing `now`."""
    if period == "weekly":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end = (start + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=0)
        return start, end

    # monthly
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_day = calendar.monthrange(now.year, now.month)[1]
    end = now.replace(day=last_day, hour=23, minute=59, second=59, microsecond=0)
    return start, end


def compute_spent(db: Session, user_id: int, category: str, start_date: datetime, end_date: datetime) -> float:
    """
    Budgets (limit_amount) are always in the home currency, so spend per
    currency is converted before combining — a plain SUM would otherwise
    add raw INR and USD amounts together.
    """
    rows = db.query(Transaction.currency, func.coalesce(func.sum(Transaction.amount), 0.0)).filter(
        Transaction.user_id == user_id,
        Transaction.category == category,
        Transaction.type == "debit",
        Transaction.date >= start_date,
        Transaction.date <= end_date
    ).group_by(Transaction.currency).all()

    return sum(to_home_currency(float(total or 0.0), currency, start_date.date()) for currency, total in rows)


class BudgetService:
    @staticmethod
    def create_budget(db: Session, user_id: int, category: str, limit_amount: float, period: str) -> Budget:
        now = now_ist()
        start_date, end_date = current_period_dates(period, now)

        # Block only when a same-category, same-period budget is *currently
        # active* — i.e. one that list_active_budgets would actually show.
        # The old check rejected any date-range overlap regardless of period
        # or whether the budget had already ended, so a long-expired weekly
        # budget could still overlap this month's window and 409 a new
        # monthly budget that the user could never see to delete.
        existing = db.query(Budget).filter(
            Budget.user_id == user_id,
            Budget.category == category,
            Budget.period == period,
            Budget.start_date <= now,
            Budget.end_date >= now
        ).first()
        if existing:
            raise DuplicateBudgetError()

        budget = Budget(
            user_id=user_id,
            category=category,
            limit_amount=limit_amount,
            spent_amount=0,
            period=period,
            start_date=start_date,
            end_date=end_date
        )
        db.add(budget)
        db.commit()
        db.refresh(budget)
        return budget

    @staticmethod
    def list_active_budgets(db: Session, user_id: int) -> list[Budget]:
        now = now_ist()
        return db.query(Budget).filter(
            Budget.user_id == user_id,
            Budget.start_date <= now,
            Budget.end_date >= now
        ).order_by(Budget.category).all()

    @staticmethod
    def get_budget(db: Session, user_id: int, budget_id: int) -> Budget:
        return db.query(Budget).filter(Budget.id == budget_id, Budget.user_id == user_id).first()

    @staticmethod
    def update_limit(db: Session, budget: Budget, limit_amount: float) -> Budget:
        budget.limit_amount = limit_amount
        db.commit()
        db.refresh(budget)
        return budget

    @staticmethod
    def delete_budget(db: Session, budget: Budget) -> None:
        db.delete(budget)
        db.commit()

    @staticmethod
    def to_response(db: Session, budget: Budget) -> dict:
        spent = compute_spent(db, budget.user_id, budget.category, budget.start_date, budget.end_date)
        return {
            "id": budget.id,
            "user_id": budget.user_id,
            "category": budget.category,
            "limit_amount": budget.limit_amount,
            "spent_amount": spent,
            "period": budget.period,
            "start_date": budget.start_date,
            "end_date": budget.end_date
        }
