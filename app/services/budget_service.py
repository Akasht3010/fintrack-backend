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

    return round(sum(to_home_currency(float(total or 0.0), currency, start_date.date()) for currency, total in rows), 2)


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

        # A budget created mid-period should already account for spend that
        # happened earlier in the same window, so seed the stored figure
        # instead of starting at 0.
        budget = Budget(
            user_id=user_id,
            category=category,
            limit_amount=limit_amount,
            spent_amount=compute_spent(db, user_id, category, start_date, end_date),
            period=period,
            start_date=start_date,
            end_date=end_date
        )
        db.add(budget)
        db.commit()
        db.refresh(budget)
        return budget

    @staticmethod
    def refresh_spent(db: Session, budgets: list[Budget]) -> bool:
        """Recompute each budget's stored spent_amount from its transactions.
        Commits only if something actually changed. Returns whether it did."""
        changed = False
        for budget in budgets:
            fresh = compute_spent(db, budget.user_id, budget.category, budget.start_date, budget.end_date)
            if fresh != budget.spent_amount:
                budget.spent_amount = fresh
                changed = True
        if changed:
            db.commit()
        return changed

    @staticmethod
    def sync_for_categories(db: Session, user_id: int, categories) -> None:
        """Re-materialize spent_amount for this user's budgets in the given
        categories. Call after any change to that user's transactions so the
        stored column stays equal to what the API/UI shows. A `str` or any
        iterable of category names is accepted; falsy entries are ignored."""
        if isinstance(categories, str):
            categories = [categories]
        names = {c for c in categories if c}
        if not names:
            return
        budgets = db.query(Budget).filter(
            Budget.user_id == user_id,
            Budget.category.in_(names)
        ).all()
        BudgetService.refresh_spent(db, budgets)

    @staticmethod
    def list_active_budgets(db: Session, user_id: int) -> list[Budget]:
        now = now_ist()
        budgets = db.query(Budget).filter(
            Budget.user_id == user_id,
            Budget.start_date <= now,
            Budget.end_date >= now
        ).order_by(Budget.category).all()
        # Safety net + one-time backfill for rows written before spent_amount
        # was materialized: guarantee the stored column matches what this
        # response reports. A no-op write-wise once everything's in sync.
        BudgetService.refresh_spent(db, budgets)
        return budgets

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
    def to_response(budget: Budget) -> dict:
        return {
            "id": budget.id,
            "user_id": budget.user_id,
            "category": budget.category,
            "limit_amount": budget.limit_amount,
            "spent_amount": budget.spent_amount,
            "period": budget.period,
            "start_date": budget.start_date,
            "end_date": budget.end_date
        }
