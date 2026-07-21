from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
import calendar
import uuid

from app.models.budget import Budget
from app.models.transaction import Transaction


class DuplicateBudgetError(Exception):
    """Raised when creating a budget that overlaps an existing one for the same category."""
    pass


def current_period_dates(period: str, now: datetime) -> tuple[datetime, datetime]:
    """Compute the start/end of the current week or month, containing `now`."""
    if period == "weekly":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end = (start + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=999999)
        return start, end

    # monthly
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_day = calendar.monthrange(now.year, now.month)[1]
    end = now.replace(day=last_day, hour=23, minute=59, second=59, microsecond=999999)
    return start, end


def compute_spent(db: Session, user_id: str, category: str, start_date: datetime, end_date: datetime) -> float:
    total = db.query(func.coalesce(func.sum(Transaction.amount), 0.0)).filter(
        Transaction.user_id == user_id,
        Transaction.category == category,
        Transaction.type == "debit",
        Transaction.date >= start_date,
        Transaction.date <= end_date
    ).scalar()
    return float(total or 0.0)


class BudgetService:
    @staticmethod
    def create_budget(db: Session, user_id: str, category: str, limit_amount: float, period: str) -> Budget:
        now = datetime.utcnow()
        start_date, end_date = current_period_dates(period, now)

        overlapping = db.query(Budget).filter(
            Budget.user_id == user_id,
            Budget.category == category,
            Budget.start_date <= end_date,
            Budget.end_date >= start_date
        ).first()
        if overlapping:
            raise DuplicateBudgetError()

        budget = Budget(
            id=str(uuid.uuid4()),
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
    def list_active_budgets(db: Session, user_id: str) -> list[Budget]:
        now = datetime.utcnow()
        return db.query(Budget).filter(
            Budget.user_id == user_id,
            Budget.start_date <= now,
            Budget.end_date >= now
        ).order_by(Budget.category).all()

    @staticmethod
    def get_budget(db: Session, user_id: str, budget_id: str) -> Budget:
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
