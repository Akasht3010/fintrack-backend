from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.config.database import get_db
from app.models.user import User
from app.models.transaction import Transaction
from app.schemas.sms import SmsSyncRequest, SmsSyncResponse
from app.services.email_parser import parse_bank_email
from app.services.categorizer import categorize_merchant
from app.services.budget_service import BudgetService
from app.utils.auth import get_current_user
from app.utils.timezone import IST

router = APIRouter(prefix="/api/sms", tags=["sms"])


@router.post("/sync", response_model=SmsSyncResponse)
async def sync_sms_messages(
    payload: SmsSyncRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Parse bank-alert SMS the app read from the device's inbox (Android only —
    the backend has no access to a user's SMS itself, so the client reads and
    posts them here). Reuses the same best-effort parser as Gmail import,
    since Indian bank SMS and email alerts use near-identical phrasing.
    """
    imported = 0
    skipped_duplicate = 0
    skipped_unparsed = 0
    seen_this_sync: list[tuple[float, datetime]] = []
    affected_categories = set()

    # One purchase can produce an SMS and one or more emails minutes apart —
    # collapse same-amount hits within this window (any source) to one row.
    DEDUP_WINDOW = timedelta(minutes=10)

    for message in payload.messages:
        body = message.body or ""
        sms_date = datetime.fromtimestamp(message.date / 1000, tz=IST).replace(tzinfo=None, microsecond=0)
        marker = f"sms:{message.address}:{message.date}"

        already_exists = db.query(Transaction).filter(
            Transaction.user_id == current_user.id,
            Transaction.raw_text == marker
        ).first()
        if already_exists:
            skipped_duplicate += 1
            continue

        parsed = parse_bank_email(subject="", body=body, snippet="", sender=message.address or "")
        if not parsed:
            skipped_unparsed += 1
            continue

        window_secs = DEDUP_WINDOW.total_seconds()
        if any(
            amt == parsed["amount"] and abs((seen - sms_date).total_seconds()) <= window_secs
            for amt, seen in seen_this_sync
        ):
            skipped_duplicate += 1
            continue

        duplicate_nearby = db.query(Transaction).filter(
            Transaction.user_id == current_user.id,
            Transaction.amount == parsed["amount"],
            Transaction.date >= sms_date - DEDUP_WINDOW,
            Transaction.date <= sms_date + DEDUP_WINDOW,
        ).first()
        if duplicate_nearby:
            skipped_duplicate += 1
            continue

        seen_this_sync.append((parsed["amount"], sms_date))

        transaction = Transaction(
            user_id=current_user.id,
            amount=parsed["amount"],
            currency="INR",
            type=parsed["type"],
            category=categorize_merchant(parsed["merchant"], parsed["description"]),
            merchant=parsed["merchant"],
            description=parsed["description"],
            date=sms_date,
            source="sms",
            raw_text=marker,
            is_recurring=False
        )
        db.add(transaction)
        try:
            db.commit()
            imported += 1
            affected_categories.add(transaction.category)
        except IntegrityError:
            # Same race as Gmail sync: a concurrent/retried sync inserted
            # this (user_id, raw_text) marker first. The unique index
            # catches it — count as a duplicate rather than failing.
            db.rollback()
            skipped_duplicate += 1

    BudgetService.sync_for_categories(db, current_user.id, affected_categories)

    return SmsSyncResponse(
        imported=imported,
        skipped_duplicate=skipped_duplicate,
        skipped_unparsed=skipped_unparsed
    )
