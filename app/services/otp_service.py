import hashlib
import hmac
import os
import secrets
from datetime import timedelta
from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.models.otp_code import OtpCode
from app.models.user import User
from app.services.email_service import send_otp_email
from app.utils.timezone import now_ist

OTP_EXPIRE_MINUTES = int(os.getenv("OTP_EXPIRE_MINUTES", "5"))
OTP_RESEND_COOLDOWN_SECONDS = int(os.getenv("OTP_RESEND_COOLDOWN_SECONDS", "30"))
MAX_OTP_ATTEMPTS = 5

# An email change's code goes to the *new* address, which is carried in the
# purpose itself ("email_change:<address>") — so a code issued for one
# address can never confirm a different one, and /resend-otp (which only
# knows the purpose) sends to the right inbox.
EMAIL_CHANGE_PURPOSE_PREFIX = "email_change:"


def email_change_purpose(new_email: str) -> str:
    return f"{EMAIL_CHANGE_PURPOSE_PREFIX}{new_email}"


def _recipient(user: User, purpose: str) -> str:
    if purpose.startswith(EMAIL_CHANGE_PURPOSE_PREFIX):
        return purpose[len(EMAIL_CHANGE_PURPOSE_PREFIX):]
    return user.email


class OtpError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code


def _hash_code(code: str, user_id: int) -> str:
    return hashlib.sha256(f"{user_id}:{code}".encode()).hexdigest()


def _generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def issue_otp(db: Session, user: User, purpose: str, background_tasks: Optional[BackgroundTasks] = None) -> None:
    """Create a fresh OTP for the user and email it. Rejects rapid re-requests
    (e.g. someone mashing "resend") rather than a genuine expiry.

    The email send is a blocking SMTP call (a Gmail TLS handshake alone can
    take several seconds) — when background_tasks is supplied, it runs after
    the HTTP response is sent instead of holding the request open, which is
    what was pushing slower requests (extra network hops from a physical
    device) past the client's timeout."""
    latest = (
        db.query(OtpCode)
        .filter(OtpCode.user_id == user.id, OtpCode.purpose == purpose, OtpCode.consumed == False)  # noqa: E712
        .order_by(OtpCode.created_at.desc())
        .first()
    )
    if latest and latest.created_at:
        elapsed = now_ist() - latest.created_at
        if elapsed < timedelta(seconds=OTP_RESEND_COOLDOWN_SECONDS):
            wait = OTP_RESEND_COOLDOWN_SECONDS - int(elapsed.total_seconds())
            raise OtpError(f"Please wait {wait}s before requesting another code", status_code=429)

    code = _generate_code()
    otp = OtpCode(
        user_id=user.id,
        purpose=purpose,
        code_hash=_hash_code(code, user.id),
        expires_at=now_ist() + timedelta(minutes=OTP_EXPIRE_MINUTES),
    )
    db.add(otp)
    db.commit()

    to_email = _recipient(user, purpose)
    if background_tasks is not None:
        background_tasks.add_task(send_otp_email, to_email=to_email, name=user.name, code=code)
    else:
        send_otp_email(to_email=to_email, name=user.name, code=code)


def verify_otp(db: Session, user_id: int, code: str, purpose: str) -> None:
    """Raises OtpError on any failure; returns normally on success (and marks
    the code consumed so it can't be replayed)."""
    otp = (
        db.query(OtpCode)
        .filter(OtpCode.user_id == user_id, OtpCode.purpose == purpose, OtpCode.consumed == False)  # noqa: E712
        .order_by(OtpCode.created_at.desc())
        .first()
    )
    if not otp:
        raise OtpError("No pending verification code. Please request a new one.")

    if now_ist() > otp.expires_at:
        raise OtpError("This code has expired. Please request a new one.")

    # Reserve an attempt *before* comparing, with one conditional UPDATE.
    # Read-check-then-increment let a burst of concurrent guesses all see
    # attempts < MAX and all get compared; now only MAX requests can ever
    # win a reservation, however many arrive at once.
    reserved = db.query(OtpCode).filter(
        OtpCode.id == otp.id, OtpCode.attempts < MAX_OTP_ATTEMPTS
    ).update({OtpCode.attempts: OtpCode.attempts + 1}, synchronize_session=False)
    db.commit()
    if not reserved:
        raise OtpError("Too many incorrect attempts. Please request a new code.")

    if not hmac.compare_digest(otp.code_hash, _hash_code((code or "").strip(), user_id)):
        raise OtpError("Incorrect code. Please try again.")

    # Same idea for redemption: only one concurrent request can flip
    # consumed, so a correct code can't be replayed in parallel.
    consumed = db.query(OtpCode).filter(
        OtpCode.id == otp.id, OtpCode.consumed == False  # noqa: E712
    ).update({OtpCode.consumed: True}, synchronize_session=False)
    db.commit()
    if not consumed:
        raise OtpError("No pending verification code. Please request a new one.")
