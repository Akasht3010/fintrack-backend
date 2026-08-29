import os
import smtplib
import ssl
import time
from email.mime.text import MIMEText

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM = os.getenv("SMTP_FROM") or SMTP_USER or "noreply@fintrack.local"
OTP_EXPIRE_MINUTES = os.getenv("OTP_EXPIRE_MINUTES", "5")

# Outcome of the last real send attempt — not a synthetic ping. OTP emails
# are often sent from a BackgroundTask (see otp_service.issue_otp), where an
# exception is only ever visible in server logs, never in the HTTP response
# the user got. This is how the admin dashboard surfaces "SMTP is silently
# broken" instead of that going unnoticed indefinitely.
_last_status: dict = {"ok": None, "checked_at": None, "error": None}


def get_smtp_status() -> dict:
    return dict(_last_status)


def send_otp_email(to_email: str, name: str, code: str) -> None:
    """Send a login OTP by email. Falls back to printing the code when SMTP
    isn't configured, so the flow is testable before a real mailbox is wired up."""
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
        print(f"\n\U0001F4E7 [DEV] No SMTP configured — OTP for {to_email}: {code}\n")
        return

    subject = "Your FinTrack verification code"
    body = (
        f"Hi {name},\n\n"
        f"Your FinTrack verification code is: {code}\n"
        f"It expires in {OTP_EXPIRE_MINUTES} minutes.\n\n"
        "If you didn't request this, you can safely ignore this email."
    )

    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = SMTP_FROM
    message["To"] = to_email

    context = ssl.create_default_context()
    try:
        # Explicit timeout: without one, a stalled connection to Gmail hangs
        # the thread indefinitely instead of failing loudly.
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls(context=context)
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, [to_email], message.as_string())
    except Exception as e:
        _last_status.update({"ok": False, "checked_at": time.time(), "error": str(e)})
        raise
    else:
        _last_status.update({"ok": True, "checked_at": time.time(), "error": None})
