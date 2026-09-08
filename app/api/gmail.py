import os
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

from app.config.database import get_db
from app.services.gmail_service import GmailService
from app.services.user_service import UserService
from app.services.email_parser import parse_bank_email
from app.services.categorizer import categorize_merchant
from app.services.budget_service import BudgetService
from app.models.user import User
from app.models.transaction import Transaction
from app.utils.auth import get_current_user, verify_token
from app.utils.crypto import decrypt
from app.utils.oauth_state import create_state, consume_state
from app.utils.timezone import now_ist, to_ist_naive

router = APIRouter(prefix="/api/gmail", tags=["gmail"])

gmail_service = GmailService()

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
CALLBACK_PATH = "/api/gmail/callback"


@router.get("/authorize")
async def gmail_authorize(
    token: str = Query(..., description="The user's own access token, so we know whose account to attach Gmail to"),
    app_redirect_uri: str = Query(...)
):
    """Kick off Gmail's OAuth consent flow (readonly inbox access) for the current user."""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    # user_id and app_redirect_uri are bound server-side to a random nonce
    # rather than round-tripped through the client-decodable `state` blob —
    # the old base64-JSON `state` was forgeable, so a crafted callback could
    # attach an attacker's Gmail grant to an arbitrary victim's user_id.
    state = create_state({"user_id": user_id, "app_redirect_uri": app_redirect_uri})
    auth_url = gmail_service.get_auth_url(f"{PUBLIC_BASE_URL}{CALLBACK_PATH}", state)
    return RedirectResponse(auth_url)


@router.get("/callback")
async def gmail_callback(code: str, state: str, db: Session = Depends(get_db)):
    """Google redirects here after Gmail consent. Exchange the code, save the refresh token, bounce back to the app."""
    pending = consume_state(state)
    if pending is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    user_id = pending["user_id"]
    app_redirect_uri = pending["app_redirect_uri"]

    try:
        refresh_token = gmail_service.exchange_code_for_token(code, f"{PUBLIC_BASE_URL}{CALLBACK_PATH}")
    except Exception as e:
        separator = "&" if "?" in app_redirect_uri else "?"
        return RedirectResponse(f"{app_redirect_uri}{separator}gmail_connected=false&error={str(e)}")

    UserService.update_gmail_token(db, user_id, refresh_token)

    separator = "&" if "?" in app_redirect_uri else "?"
    return RedirectResponse(f"{app_redirect_uri}{separator}gmail_connected=true")


@router.post("/disconnect")
async def gmail_disconnect(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Disconnect Gmail: best-effort revoke with Google, then clear the stored token either way."""
    if current_user.gmail_refresh_token:
        try:
            gmail_service.revoke_token(decrypt(current_user.gmail_refresh_token))
        except Exception:
            pass

    current_user.gmail_connected = False
    current_user.gmail_refresh_token = None
    db.commit()

    return {"gmail_connected": False}

@router.post("/sync")
async def sync_gmail_emails(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Fetch bank alert emails and create transactions from the ones we can parse. Skips emails already imported."""
    if not current_user.gmail_connected or not current_user.gmail_refresh_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gmail not connected")

    try:
        emails = gmail_service.search_bank_emails(decrypt(current_user.gmail_refresh_token))
    except Exception as e:
        # Google expires refresh tokens after 7 days for OAuth apps still in
        # "Testing" publishing status (ours is, pending verification) — this
        # is expected, recurring behavior, not a transient failure. Treat it
        # as a stale connection: clear it server-side too, so the client
        # isn't left showing "connected" for a token that no longer works.
        if "invalid_grant" in str(e):
            current_user.gmail_connected = False
            current_user.gmail_refresh_token = None
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Your Gmail connection expired. Please reconnect Gmail from Profile."
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Couldn't reach Gmail: {str(e)}"
        )

    imported = 0
    skipped_duplicate = 0
    skipped_unparsed = 0
    seen_this_sync: list[tuple[float, datetime]] = []
    affected_categories = set()

    # One real purchase often generates several emails minutes apart — the
    # bank alert, the card-network alert, the UPI-app receipt, the merchant
    # receipt — each a distinct message. Collapse anything with the same
    # amount within this window (regardless of source) to a single row.
    DEDUP_WINDOW = timedelta(minutes=10)

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
            # parsedate_to_datetime returns a tz-aware datetime carrying the
            # sender's offset, but the `date` column is naive IST (same as
            # every other source) — storing it as-is would skew this
            # transaction's date by that offset, corrupting budget-period
            # bucketing, monthly insights, and recurring-cadence detection.
            email_date = to_ist_naive(email_date)
        except Exception:
            email_date = now_ist()

        window_secs = DEDUP_WINDOW.total_seconds()
        if any(
            amt == parsed["amount"] and abs((seen - email_date).total_seconds()) <= window_secs
            for amt, seen in seen_this_sync
        ):
            skipped_duplicate += 1
            continue

        duplicate_nearby = db.query(Transaction).filter(
            Transaction.user_id == current_user.id,
            Transaction.amount == parsed["amount"],
            Transaction.date >= email_date - DEDUP_WINDOW,
            Transaction.date <= email_date + DEDUP_WINDOW,
        ).first()
        if duplicate_nearby:
            skipped_duplicate += 1
            continue

        seen_this_sync.append((parsed["amount"], email_date))

        transaction = Transaction(
            user_id=current_user.id,
            amount=parsed["amount"],
            currency="INR",
            type=parsed["type"],
            category=categorize_merchant(parsed["merchant"], parsed["description"]),
            merchant=parsed["merchant"],
            description=parsed["description"],
            date=email_date,
            source="gmail",
            raw_text=marker,
            is_recurring=False
        )
        db.add(transaction)
        try:
            db.commit()
            imported += 1
            affected_categories.add(transaction.category)
        except IntegrityError:
            # A concurrent sync (or retried request) inserted the same
            # (user_id, raw_text) marker first — the unique index catches
            # what the check above raced against. Treat it as a duplicate,
            # not a failure.
            db.rollback()
            skipped_duplicate += 1

    BudgetService.sync_for_categories(db, current_user.id, affected_categories)

    return {
        "imported": imported,
        "skipped_duplicate": skipped_duplicate,
        "skipped_unparsed": skipped_unparsed
    }
