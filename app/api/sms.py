from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.config.database import get_db
from app.models.user import User
from app.models.transaction import Transaction
from app.schemas.sms import SmsSyncRequest, SmsSyncResponse
from app.schemas.transaction import MAX_TRANSACTION_AMOUNT
from app.services.email_parser import parse_bank_email
from app.services.categorizer import categorize_merchant
from app.services.import_dedup import ImportDeduper
from app.services.budget_service import BudgetService
from app.utils.auth import get_current_user
from app.utils.timezone import IST

router = APIRouter(prefix="/api/sms", tags=["sms"])


@router.post("/sync", response_model=SmsSyncResponse)
def sync_sms_messages(
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
    deduper = ImportDeduper(db, current_user.id)
    affected_categories = set()

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

        # Same ceiling manual entry gets via the schema — this path builds
        # the ORM row directly and would otherwise let a mis-parsed or
        # adversarial amount string through unbounded.
        if parsed["amount"] > MAX_TRANSACTION_AMOUNT:
            skipped_unparsed += 1
            continue

        if deduper.is_duplicate(parsed["amount"], parsed["type"], sms_date):
            skipped_duplicate += 1
            continue
        deduper.record(parsed["amount"], parsed["type"], sms_date)

        transaction = Transaction(
            user_id=current_user.id,
            amount=parsed["amount"],
            currency="INR",
            type=parsed["type"],
            category=parsed.get("category") or categorize_merchant(parsed["merchant"], parsed["description"]),
            merchant=parsed["merchant"],
            description=parsed["description"],
            date=sms_date,
            source="sms",
            raw_text=marker,
            is_recurring=False
        )
        db.add(transaction)
        try:
            # Committed per-message on purpose, same rationale as Gmail
            # sync: a failure further down the loop should never roll back
            # messages already counted as imported in this response.
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
