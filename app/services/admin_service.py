import os
import time
from datetime import timedelta

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.config.database import engine
from app.models.account import Account
from app.models.budget import Budget
from app.models.otp_code import OtpCode
from app.models.transaction import Transaction
from app.models.user import User
from app.services.email_service import get_smtp_status
from app.services.exchange_rate_service import to_home_currency, get_fx_status
from app.utils.timezone import now_ist

# Set once at import time (main.py imports the admin router at startup),
# close enough to process start for an uptime figure a dashboard polls.
APP_START_TIME = time.time()

DAILY_SERIES_DAYS = 14

# Railway sets this automatically on every deploy — no manual wiring needed.
# Falls back to "local" outside Railway (e.g. running via `python run.py`).
DEPLOYED_VERSION = os.getenv("RAILWAY_GIT_COMMIT_SHA", "")[:7] or "local"


def _db_size_bytes(db: Session) -> int | None:
    """Best-effort — not critical enough to fail health over, so any error
    here just surfaces as null rather than a 500."""
    try:
        if engine.dialect.name == "postgresql":
            return db.execute(text("SELECT pg_database_size(current_database())")).scalar()
        if engine.dialect.name == "sqlite":
            db_path = engine.url.database
            if db_path and os.path.exists(db_path):
                return os.path.getsize(db_path)
    except Exception:
        pass
    return None


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
        "version": DEPLOYED_VERSION,
        "db_size_bytes": _db_size_bytes(db),
        "dependencies": {
            "smtp": get_smtp_status(),
            "fx_rate_api": get_fx_status(),
        },
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

    # "Active" = actually used the app recently (added a transaction), not just
    # holds an account — created_at is when the row was recorded, so this
    # tracks real activity rather than a transaction's own (possibly backdated) date.
    active_7d = (
        db.query(func.count(func.distinct(Transaction.user_id)))
        .filter(Transaction.created_at >= week_ago)
        .scalar()
    )

    # Signed up more than a week ago (past the grace period a brand-new user
    # deserves) and never logged a single transaction — a churn/onboarding-drop signal.
    users_with_any_transaction = db.query(Transaction.user_id).distinct().subquery()
    dead_signups = (
        db.query(func.count(User.id))
        .filter(User.created_at < week_ago)
        .filter(~User.id.in_(db.query(users_with_any_transaction.c.user_id)))
        .scalar()
    )

    total_transactions = db.query(func.count(Transaction.id)).scalar()
    transactions_today = (
        db.query(func.count(Transaction.id)).filter(Transaction.created_at >= today_start).scalar()
    )
    by_source_rows = db.query(Transaction.source, func.count(Transaction.id)).group_by(Transaction.source).all()

    total_accounts = db.query(func.count(Account.id)).scalar()
    total_budgets = db.query(func.count(Budget.id)).scalar()
    users_with_budget = db.query(func.count(func.distinct(Budget.user_id))).scalar()
    budget_adoption_pct = round((users_with_budget / total_users * 100), 1) if total_users else 0.0

    otp_issued_7d = db.query(func.count(OtpCode.id)).filter(OtpCode.created_at >= week_ago).scalar()
    otp_consumed_7d = (
        db.query(func.count(OtpCode.id))
        .filter(OtpCode.created_at >= week_ago, OtpCode.consumed == True)  # noqa: E712
        .scalar()
    )
    otp_expired_7d = (
        db.query(func.count(OtpCode.id))
        .filter(OtpCode.created_at >= week_ago, OtpCode.consumed == False, OtpCode.expires_at < now)  # noqa: E712
        .scalar()
    )

    # Connected but quiet: gmail_connected users with no gmail-sourced
    # transaction in the last week — either sync is broken (revoked token)
    # or they just haven't opened the app; this can't tell the two apart,
    # it's a "worth checking" signal, not a definitive fault.
    last_gmail_tx_by_user = (
        db.query(Transaction.user_id, func.max(Transaction.created_at).label("last_at"))
        .filter(Transaction.source == "gmail")
        .group_by(Transaction.user_id)
        .subquery()
    )
    gmail_stale_connections = (
        db.query(func.count(User.id))
        .outerjoin(last_gmail_tx_by_user, User.id == last_gmail_tx_by_user.c.user_id)
        .filter(User.gmail_connected == True)  # noqa: E712
        .filter((last_gmail_tx_by_user.c.last_at == None) | (last_gmail_tx_by_user.c.last_at < week_ago))  # noqa: E711
        .scalar()
    )

    top_categories = _top_categories(db)

    return {
        "users": {
            "total": total_users,
            "new_today": new_today,
            "new_7d": new_7d,
            "new_30d": new_30d,
            "gmail_connected": gmail_connected,
            "active_7d": active_7d,
            "dead_signups": dead_signups,
        },
        "transactions": {
            "total": total_transactions,
            "today": transactions_today,
            "by_source": {source: count for source, count in by_source_rows},
        },
        "accounts_total": total_accounts,
        "budgets_total": total_budgets,
        "budget_adoption_pct": budget_adoption_pct,
        "otp": {
            "issued_7d": otp_issued_7d,
            "consumed_7d": otp_consumed_7d,
            "expired_7d": otp_expired_7d,
        },
        "gmail_stale_connections": gmail_stale_connections,
        "top_categories": top_categories,
        "signups_by_day": _daily_counts(db, User.created_at, DAILY_SERIES_DAYS),
        "transactions_by_day": _daily_counts(db, Transaction.created_at, DAILY_SERIES_DAYS),
    }


def _top_categories(db: Session, limit: int = 5) -> list[dict]:
    """Top categories by transaction count, with amounts converted to the
    home currency (see exchange_rate_service) since transactions can be
    logged in whatever currency they actually happened in — summing raw
    amounts across currencies would be meaningless."""
    counts = (
        db.query(Transaction.category, func.count(Transaction.id))
        .group_by(Transaction.category)
        .order_by(func.count(Transaction.id).desc())
        .limit(limit)
        .all()
    )

    result = []
    for category, count in counts:
        rows = (
            db.query(Transaction.amount, Transaction.currency, Transaction.date)
            .filter(Transaction.category == category)
            .all()
        )
        total = sum(
            to_home_currency(amount, currency, on_date=d.date() if d else None) for amount, currency, d in rows
        )
        result.append({"category": category, "count": count, "total_amount": round(total, 2)})
    return result
