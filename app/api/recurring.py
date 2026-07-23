from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.user import User
from app.schemas.recurring import RecurringItem, RecurringSummary
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
    monthly_total = sum(item["average_amount"] * MONTHLY_EQUIVALENT[item["cadence"]] for item in items)

    return RecurringSummary(
        items=[RecurringItem(**item) for item in items],
        monthly_total=round(monthly_total, 2)
    )
