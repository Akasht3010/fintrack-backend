from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.user import User
from app.schemas.recurring import RecurringItem, RecurringSummary
from app.services.exchange_rate_service import to_home_currency
from app.services.recurring_service import MONTHLY_EQUIVALENT, detect_recurring
from app.utils.auth import get_current_user

router = APIRouter(prefix="/api/recurring", tags=["recurring"])

@router.get("", response_model=RecurringSummary)
async def get_recurring(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Detected recurring bills/subscriptions for the authenticated user,
    inferred from spacing and amount consistency across past transactions."""
    items = detect_recurring(db, current_user.id)
    # Each item stays in its own billing currency (average_amount/currency),
    # but the combined total is a single home-currency figure, so each
    # item's monthly-equivalent cost is converted before summing — using
    # today's rate since this represents an ongoing commitment, not a
    # historical record.
    today = date.today()
    monthly_total = sum(
        to_home_currency(item["average_amount"] * MONTHLY_EQUIVALENT[item["cadence"]], item["currency"], today)
        for item in items
    )

    return RecurringSummary(
        items=[RecurringItem(**item) for item in items],
        monthly_total=round(monthly_total, 2)
    )
