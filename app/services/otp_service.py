import hashlib
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.models.otp_code import OtpCode
from app.models.user import User
from app.services.email_service import send_otp_email

OTP_EXPIRE_MINUTES = int(os.getenv("OTP_EXPIRE_MINUTES", "5"))
OTP_RESEND_COOLDOWN_SECONDS = int(os.getenv("OTP_RESEND_COOLDOWN_SECONDS", "30"))
MAX_OTP_ATTEMPTS = 5


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
        elapsed = datetime.utcnow() - latest.created_at
        if elapsed < timedelta(seconds=OTP_RESEND_COOLDOWN_SECONDS):
            wait = OTP_RESEND_COOLDOWN_SECONDS - int(elapsed.total_seconds())
            raise OtpError(f"Please wait {wait}s before requesting another code", status_code=429)

    code = _generate_code()
    otp = OtpCode(
        user_id=user.id,
        purpose=purpose,
        code_hash=_hash_code(code, user.id),
        expires_at=datetime.utcnow() + timedelta(minutes=OTP_EXPIRE_MINUTES),
    )
    db.add(otp)
    db.commit()

    if background_tasks is not None:
        background_tasks.add_task(send_otp_email, to_email=user.email, name=user.name, code=code)
    else:
        send_otp_email(to_email=user.email, name=user.name, code=code)


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

    if datetime.utcnow() > otp.expires_at:
        raise OtpError("This code has expired. Please request a new one.")

    if otp.attempts >= MAX_OTP_ATTEMPTS:
        raise OtpError("Too many incorrect attempts. Please request a new code.")

    if otp.code_hash != _hash_code((code or "").strip(), user_id):
        otp.attempts += 1
        db.commit()
        raise OtpError("Incorrect code. Please try again.")

    otp.consumed = True
    db.commit()
