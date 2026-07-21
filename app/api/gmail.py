import base64
import json
import os
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime
from email.utils import parsedate_to_datetime

from app.config.database import get_db
from app.services.gmail_service import GmailService
from app.services.user_service import UserService
from app.services.email_parser import parse_bank_email
from app.models.user import User
from app.models.transaction import Transaction
from app.utils.auth import get_current_user, verify_token

router = APIRouter(prefix="/api/gmail", tags=["gmail"])

gmail_service = GmailService()

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
CALLBACK_PATH = "/api/gmail/callback"


def _encode_state(user_id: str, app_redirect_uri: str) -> str:
    payload = json.dumps({"user_id": user_id, "app_redirect_uri": app_redirect_uri})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_state(state: str) -> dict:
    try:
        return json.loads(base64.urlsafe_b64decode(state.encode()).decode())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid state")


@router.get("/authorize")
async def gmail_authorize(
    token: str = Query(..., description="The user's own access token, so we know whose account to attach Gmail to"),
    app_redirect_uri: str = Query(...)
):
    """Kick off Gmail's OAuth consent flow (readonly inbox access) for the current user."""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    state = _encode_state(user_id, app_redirect_uri)
    auth_url = gmail_service.get_auth_url(f"{PUBLIC_BASE_URL}{CALLBACK_PATH}", state)
    return RedirectResponse(auth_url)


@router.get("/callback")
async def gmail_callback(code: str, state: str, db: Session = Depends(get_db)):
    """Google redirects here after Gmail consent. Exchange the code, save the refresh token, bounce back to the app."""
    decoded = _decode_state(state)
    user_id = decoded["user_id"]
    app_redirect_uri = decoded["app_redirect_uri"]

    try:
        refresh_token = gmail_service.exchange_code_for_token(code, f"{PUBLIC_BASE_URL}{CALLBACK_PATH}")
    except Exception as e:
        separator = "&" if "?" in app_redirect_uri else "?"
        return RedirectResponse(f"{app_redirect_uri}{separator}gmail_connected=false&error={str(e)}")

    UserService.update_gmail_token(db, user_id, refresh_token)

    separator = "&" if "?" in app_redirect_uri else "?"
    return RedirectResponse(f"{app_redirect_uri}{separator}gmail_connected=true")


@router.post("/sync")
async def sync_gmail_emails(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Fetch bank alert emails and create transactions from the ones we can parse. Skips emails already imported."""
    if not current_user.gmail_connected or not current_user.gmail_refresh_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gmail not connected")

    try:
        emails = gmail_service.search_bank_emails(current_user.gmail_refresh_token)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Couldn't reach Gmail: {str(e)}"
        )

    imported = 0
    skipped_duplicate = 0
    skipped_unparsed = 0
    seen_this_sync = set()

    for email in emails:
        marker = f"gmail:{email['id']}"

        already_exists = db.query(Transaction).filter(
            Transaction.user_id == current_user.id,
            Transaction.raw_text == marker
        ).first()
        if already_exists:
            skipped_duplicate += 1
            continue

        parsed = parse_bank_email(
            subject=email.get("subject", ""),
            body=email.get("body", ""),
            snippet=email.get("snippet", ""),
            sender=email.get("from", "")
        )
        if not parsed:
            skipped_unparsed += 1
            continue

        try:
            email_date = parsedate_to_datetime(email["date"])
        except Exception:
            email_date = datetime.utcnow()

        # Some banks send multiple emails for the same underlying transaction
        # (e.g. a generic alert + a separate fee notice) with different
        # message IDs but the same amount and timestamp — catch those too,
        # both within this sync batch and against already-imported ones.
        dedup_key = (parsed["amount"], email_date)
        if dedup_key in seen_this_sync:
            skipped_duplicate += 1
            continue

        duplicate_amount_date = db.query(Transaction).filter(
            Transaction.user_id == current_user.id,
            Transaction.source == "gmail",
            Transaction.amount == parsed["amount"],
            Transaction.date == email_date
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
            category="other",
            merchant=parsed["merchant"],
            description=email.get("subject", "")[:200],
            date=email_date,
            source="gmail",
            raw_text=marker,
            is_recurring=False
        )
        db.add(transaction)
        imported += 1

    db.commit()

    return {
        "imported": imported,
        "skipped_duplicate": skipped_duplicate,
        "skipped_unparsed": skipped_unparsed
    }
