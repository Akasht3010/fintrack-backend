from calendar import month_abbr
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, extract, func
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.insights import CategoryBreakdownItem, InsightsSummary, MerchantBreakdownItem, MonthlyTotal
from app.utils.auth import get_current_user

router = APIRouter(prefix="/api/insights", tags=["insights"])

@router.get("", response_model=InsightsSummary)
async def get_insights(
    months: int = Query(6, ge=1, le=12),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Spending trends for the authenticated user: monthly totals, this month's
    category breakdown, and top merchants over the requested range."""
    now = datetime.utcnow()

    start_year = now.year
    start_month = now.month - (months - 1)
    while start_month <= 0:
        start_month += 12
        start_year -= 1
    range_start = datetime(start_year, start_month, 1)

    year_expr = extract("year", Transaction.date)
    month_expr = extract("month", Transaction.date)

    def monthly_series(transaction_type: str) -> list[MonthlyTotal]:
        rows = (
            db.query(
                year_expr.label("year"),
                month_expr.label("month"),
                func.sum(Transaction.amount).label("total")
            )
            .filter(
                Transaction.user_id == current_user.id,
                Transaction.type == transaction_type,
                Transaction.date >= range_start
            )
            .group_by(year_expr, month_expr)
            .all()
        )
        totals_by_key = {(int(r.year), int(r.month)): float(r.total) for r in rows}

        series = []
        y, m = start_year, start_month
        for _ in range(months):
            series.append(MonthlyTotal(year=y, month=m, label=month_abbr[m], total=totals_by_key.get((y, m), 0.0)))
            m += 1
            if m > 12:
                m = 1
                y += 1
        return series

    monthly_totals = monthly_series("debit")
    monthly_income_totals = monthly_series("credit")

    current_month_start = datetime(now.year, now.month, 1)
    category_rows = (
        db.query(Transaction.category, func.sum(Transaction.amount).label("total"))
        .filter(
            Transaction.user_id == current_user.id,
            Transaction.type == "debit",
            Transaction.date >= current_month_start
        )
        .group_by(Transaction.category)
        .order_by(desc("total"))
        .all()
    )
    category_breakdown = [CategoryBreakdownItem(category=r.category, total=float(r.total)) for r in category_rows]

    merchant_rows = (
        db.query(
            Transaction.merchant,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("count")
        )
        .filter(
            Transaction.user_id == current_user.id,
            Transaction.type == "debit",
            Transaction.date >= range_start
        )
        .group_by(Transaction.merchant)
        .order_by(desc("total"))
        .limit(5)
        .all()
    )
    top_merchants = [
        MerchantBreakdownItem(merchant=r.merchant, total=float(r.total), count=r.count) for r in merchant_rows
    ]

    return InsightsSummary(
        monthly_totals=monthly_totals,
        monthly_income_totals=monthly_income_totals,
        category_breakdown=category_breakdown,
        top_merchants=top_merchants
    )
