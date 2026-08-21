from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.config.database import get_db
from app.models.user import User
from app.models.transaction import Transaction
from app.schemas.sms import SmsSyncRequest, SmsSyncResponse
from app.services.email_parser import parse_bank_email
from app.services.categorizer import categorize_merchant
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
    seen_this_sync = set()

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

        # Same cross-source dedup as Gmail: a couple of banks send both an SMS
        # and an email for the same transaction — don't double-import it.
        dedup_key = (parsed["amount"], sms_date)
        if dedup_key in seen_this_sync:
            skipped_duplicate += 1
            continue

        duplicate_amount_date = db.query(Transaction).filter(
            Transaction.user_id == current_user.id,
            Transaction.amount == parsed["amount"],
            Transaction.date == sms_date
        ).first()
        if duplicate_amount_date:
            skipped_duplicate += 1
            continue

        seen_this_sync.add(dedup_key)

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
        except IntegrityError:
            # Same race as Gmail sync: a concurrent/retried sync inserted
            # this (user_id, raw_text) marker first. The unique index
            # catches it — count as a duplicate rather than failing.
            db.rollback()
            skipped_duplicate += 1

    return SmsSyncResponse(
        imported=imported,
        skipped_duplicate=skipped_duplicate,
        skipped_unparsed=skipped_unparsed
    )
