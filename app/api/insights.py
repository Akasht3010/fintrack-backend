from calendar import month_abbr
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.transaction import Transaction
from app.models.user import User
from typing import Optional

from app.models.account import Account
from app.schemas.insights import (
    AccountBreakdownItem, CategoryBreakdownItem, InsightsSummary, MerchantBreakdownItem, MonthlyTotal,
    PaymentMethodBreakdownItem,
)
from app.utils.auth import get_current_user
from app.utils.timezone import now_ist

router = APIRouter(prefix="/api/insights", tags=["insights"])

@router.get("", response_model=InsightsSummary)
def get_insights(
    months: int = Query(6, ge=1, le=12),
    account_id: Optional[int] = Query(None, ge=0, description="Only this account; 0 = not linked to any"),
    payment_method: Optional[str] = Query(None, description="Only this payment method, e.g. upi"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Spending trends for the authenticated user: monthly totals, this month's
    category breakdown, and top merchants over the requested range."""
    now = now_ist()

    start_year = now.year
    start_month = now.month - (months - 1)
    while start_month <= 0:
        start_month += 12
        start_year -= 1
    range_start = datetime(start_year, start_month, 1)

    year_expr = extract("year", Transaction.date)
    month_expr = extract("month", Transaction.date)

    # All amounts are INR, so every total below is a plain SQL SUM.
    # `transfer` rows are money moved between the user's own accounts — they
    # show up as a debit on one side and a credit on the other, netting to
    # zero, so they're left out of every spend/income figure here.
    not_a_transfer = Transaction.category != "transfer"

    # Every figure below honours the account / payment-method filter, so
    # e.g. "UPI only" lines up with what a UPI app reports as spent.
    scope = [Transaction.user_id == current_user.id, not_a_transfer]
    if account_id is not None:
        scope.append(Transaction.account_id.is_(None) if account_id == 0 else Transaction.account_id == account_id)
    if payment_method and payment_method != "all":
        scope.append(Transaction.payment_method == payment_method)

    def monthly_series(transaction_type: str) -> list[MonthlyTotal]:
        rows = (
            db.query(
                year_expr.label("year"),
                month_expr.label("month"),
                func.sum(Transaction.amount).label("total")
            )
            .filter(
                *scope,
                Transaction.type == transaction_type,
                Transaction.date >= range_start,
            )
            .group_by(year_expr, month_expr)
            .all()
        )
        totals_by_key = {(int(r.year), int(r.month)): float(r.total or 0.0) for r in rows}

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
        .filter(*scope, Transaction.type == "debit", Transaction.date >= current_month_start)
        .group_by(Transaction.category)
        .all()
    )
    category_breakdown = sorted(
        (CategoryBreakdownItem(category=r.category, total=float(r.total or 0.0)) for r in category_rows),
        key=lambda c: c.total, reverse=True
    )

    merchant_rows = (
        db.query(
            Transaction.merchant,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("count")
        )
        .filter(*scope, Transaction.type == "debit", Transaction.date >= range_start)
        .group_by(Transaction.merchant)
        .order_by(func.sum(Transaction.amount).desc())
        .limit(5)
        .all()
    )
    top_merchants = [
        MerchantBreakdownItem(merchant=r.merchant, total=float(r.total or 0.0), count=int(r.count))
        for r in merchant_rows
    ]

    this_month_debits = [*scope, Transaction.type == "debit", Transaction.date >= current_month_start]

    accounts = {a.id: a for a in db.query(Account).filter(Account.user_id == current_user.id)}
    account_rows = (
        db.query(Transaction.account_id, func.sum(Transaction.amount).label("total"))
        .filter(*this_month_debits)
        .group_by(Transaction.account_id)
        .all()
    )
    account_breakdown = sorted(
        (
            AccountBreakdownItem(
                account_id=r.account_id,
                name=accounts[r.account_id].name if r.account_id in accounts else "Not linked",
                type=accounts[r.account_id].type if r.account_id in accounts else None,
                total=float(r.total or 0.0),
            )
            for r in account_rows
        ),
        key=lambda a: a.total, reverse=True
    )

    method_rows = (
        db.query(
            Transaction.payment_method,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("count")
        )
        .filter(*this_month_debits)
        .group_by(Transaction.payment_method)
        .all()
    )
    payment_method_breakdown = sorted(
        (
            PaymentMethodBreakdownItem(payment_method=r.payment_method, total=float(r.total or 0.0), count=int(r.count))
            for r in method_rows
        ),
        key=lambda m: m.total, reverse=True
    )

    return InsightsSummary(
        monthly_totals=monthly_totals,
        monthly_income_totals=monthly_income_totals,
        category_breakdown=category_breakdown,
        top_merchants=top_merchants,
        account_breakdown=account_breakdown,
        payment_method_breakdown=payment_method_breakdown
    )
