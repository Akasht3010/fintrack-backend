from calendar import month_abbr
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.insights import CategoryBreakdownItem, InsightsSummary, MerchantBreakdownItem, MonthlyTotal
from app.services.exchange_rate_service import to_home_currency
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

    # Every query below groups by currency in addition to whatever it's
    # actually reporting on, then converts+combines per group in Python —
    # a plain SQL SUM would silently add raw INR and USD amounts together.
    # Sorting/limiting (top merchants) also has to happen after that
    # conversion, so it moves to Python too.

    def monthly_series(transaction_type: str) -> list[MonthlyTotal]:
        rows = (
            db.query(
                year_expr.label("year"),
                month_expr.label("month"),
                Transaction.currency,
                func.sum(Transaction.amount).label("total")
            )
            .filter(
                Transaction.user_id == current_user.id,
                Transaction.type == transaction_type,
                Transaction.date >= range_start
            )
            .group_by(year_expr, month_expr, Transaction.currency)
            .all()
        )
        totals_by_key: dict[tuple[int, int], float] = {}
        for r in rows:
            key = (int(r.year), int(r.month))
            converted = to_home_currency(float(r.total), r.currency, date(int(r.year), int(r.month), 1))
            totals_by_key[key] = totals_by_key.get(key, 0.0) + converted

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
        db.query(Transaction.category, Transaction.currency, func.sum(Transaction.amount).label("total"))
        .filter(
            Transaction.user_id == current_user.id,
            Transaction.type == "debit",
            Transaction.date >= current_month_start
        )
        .group_by(Transaction.category, Transaction.currency)
        .all()
    )
    category_totals: dict[str, float] = {}
    for r in category_rows:
        converted = to_home_currency(float(r.total), r.currency, current_month_start.date())
        category_totals[r.category] = category_totals.get(r.category, 0.0) + converted
    category_breakdown = sorted(
        (CategoryBreakdownItem(category=cat, total=total) for cat, total in category_totals.items()),
        key=lambda c: c.total, reverse=True
    )

    merchant_rows = (
        db.query(
            Transaction.merchant,
            Transaction.currency,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("count")
        )
        .filter(
            Transaction.user_id == current_user.id,
            Transaction.type == "debit",
            Transaction.date >= range_start
        )
        .group_by(Transaction.merchant, Transaction.currency)
        .all()
    )
    merchant_totals: dict[str, dict] = {}
    for r in merchant_rows:
        entry = merchant_totals.setdefault(r.merchant, {"total": 0.0, "count": 0})
        entry["total"] += to_home_currency(float(r.total), r.currency, range_start.date())
        entry["count"] += r.count
    top_merchants = sorted(
        (MerchantBreakdownItem(merchant=m, total=v["total"], count=v["count"]) for m, v in merchant_totals.items()),
        key=lambda x: x.total, reverse=True
    )[:5]

    return InsightsSummary(
        monthly_totals=monthly_totals,
        monthly_income_totals=monthly_income_totals,
        category_breakdown=category_breakdown,
        top_merchants=top_merchants
    )
