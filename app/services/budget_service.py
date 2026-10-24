from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
import calendar

from app.models.budget import Budget
from app.models.transaction import Transaction
from app.utils.timezone import now_ist

CENTS = Decimal("0.01")


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


def compute_spent(db: Session, user_id: int, category: str, start_date: datetime, end_date: datetime) -> Decimal:
    """Total debit spend in this category within the budget window (all INR)."""
    total = db.query(func.coalesce(func.sum(Transaction.amount), Decimal("0"))).filter(
        Transaction.user_id == user_id,
        Transaction.category == category,
        Transaction.type == "debit",
        Transaction.date >= start_date,
        Transaction.date <= end_date
    ).scalar()

    return (total or Decimal("0")).quantize(CENTS, rounding=ROUND_HALF_UP)


class BudgetService:
    @staticmethod
    def create_budget(db: Session, user_id: int, category: str, limit_amount: Decimal, period: str) -> Budget:
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
    def roll_forward(db: Session, user_id: int, now: datetime) -> None:
        """Budgets recur: a row covers one week/month, and once that window
        ends the category's budget would otherwise vanish from the app until
        the user noticed and recreated it. For each (category, period) whose
        most recent row has ended, start the current window with the same
        limit. Ended rows stay as history; deleting the budget is how a user
        stops it recurring (nothing is left to roll forward)."""
        latest: dict[tuple[str, str], Budget] = {}
        for budget in db.query(Budget).filter(Budget.user_id == user_id).order_by(Budget.end_date):
            latest[(budget.category, budget.period)] = budget

        created = False
        for (category, period), budget in latest.items():
            if budget.end_date >= now:
                continue  # still active (or, defensively, in the future)
            start_date, end_date = current_period_dates(period, now)
            db.add(Budget(
                user_id=user_id,
                category=category,
                limit_amount=budget.limit_amount,
                spent_amount=compute_spent(db, user_id, category, start_date, end_date),
                period=period,
                start_date=start_date,
                end_date=end_date
            ))
            created = True
        if created:
            db.commit()

    @staticmethod
    def list_active_budgets(db: Session, user_id: int) -> list[Budget]:
        now = now_ist()
        BudgetService.roll_forward(db, user_id, now)
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
    def update_limit(db: Session, budget: Budget, limit_amount: Decimal) -> Budget:
        budget.limit_amount = limit_amount
        db.commit()
        db.refresh(budget)
        return budget

    @staticmethod
    def delete_budget(db: Session, budget: Budget) -> None:
        # The whole (category, period) series, not just this row: an ended
        # row left behind would be rolled straight back into the current
        # period by roll_forward on the next list.
        db.query(Budget).filter(
            Budget.user_id == budget.user_id,
            Budget.category == budget.category,
            Budget.period == budget.period
        ).delete()
        db.commit()

    @staticmethod
    def to_response(budget: Budget) -> dict:
        return {
            "id": budget.id,
            "user_id": budget.user_id,
            "category": budget.category,
            "limit_amount": budget.limit_amount,
            "spent_amount": budget.spent_amount,
            "remaining_amount": budget.remaining_amount,
            "period": budget.period,
            "start_date": budget.start_date,
            "end_date": budget.end_date
        }
