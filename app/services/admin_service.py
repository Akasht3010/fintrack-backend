import time
from datetime import timedelta

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.budget import Budget
from app.models.transaction import Transaction
from app.models.user import User
from app.utils.timezone import now_ist

# Set once at import time (main.py imports the admin router at startup),
# close enough to process start for an uptime figure a dashboard polls.
APP_START_TIME = time.time()

DAILY_SERIES_DAYS = 14


def get_health(db: Session) -> dict:
    start = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"
    latency_ms = (time.perf_counter() - start) * 1000

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "uptime_seconds": time.time() - APP_START_TIME,
        "db": {"status": db_status, "latency_ms": round(latency_ms, 2)},
    }


def _daily_counts(db: Session, date_column, days: int) -> list[dict]:
    """Zero-filled per-day counts for the trailing `days` days (inclusive of
    today), so a chart doesn't have to guess whether a missing day means
    zero or missing data."""
    since = now_ist() - timedelta(days=days - 1)
    rows = (
        db.query(func.date(date_column).label("day"), func.count().label("count"))
        .filter(date_column >= since)
        .group_by("day")
        .all()
    )
    counts_by_day = {str(day): count for day, count in rows}

    result = []
    for i in range(days):
        d = (since + timedelta(days=i)).date()
        result.append({"date": d.isoformat(), "count": counts_by_day.get(str(d), 0)})
    return result


def get_stats(db: Session) -> dict:
    now = now_ist()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    total_users = db.query(func.count(User.id)).scalar()
    new_today = db.query(func.count(User.id)).filter(User.created_at >= today_start).scalar()
    new_7d = db.query(func.count(User.id)).filter(User.created_at >= week_ago).scalar()
    new_30d = db.query(func.count(User.id)).filter(User.created_at >= month_ago).scalar()
    gmail_connected = db.query(func.count(User.id)).filter(User.gmail_connected == True).scalar()  # noqa: E712

    total_transactions = db.query(func.count(Transaction.id)).scalar()
    transactions_today = (
        db.query(func.count(Transaction.id)).filter(Transaction.created_at >= today_start).scalar()
    )
    by_source_rows = db.query(Transaction.source, func.count(Transaction.id)).group_by(Transaction.source).all()

    total_accounts = db.query(func.count(Account.id)).scalar()
    total_budgets = db.query(func.count(Budget.id)).scalar()

    return {
        "users": {
            "total": total_users,
            "new_today": new_today,
            "new_7d": new_7d,
            "new_30d": new_30d,
            "gmail_connected": gmail_connected,
        },
        "transactions": {
            "total": total_transactions,
            "today": transactions_today,
            "by_source": {source: count for source, count in by_source_rows},
        },
        "accounts_total": total_accounts,
        "budgets_total": total_budgets,
        "signups_by_day": _daily_counts(db, User.created_at, DAILY_SERIES_DAYS),
        "transactions_by_day": _daily_counts(db, Transaction.created_at, DAILY_SERIES_DAYS),
    }
