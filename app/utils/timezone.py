from datetime import datetime
from zoneinfo import ZoneInfo

# Every business-data timestamp in this app (transaction date, created_at,
# updated_at, budget periods, insights bucketing) is stored as a naive IST
# wall-clock value -- deliberately not UTC, at the app owner's request, so
# the raw DB rows already read correctly without any display-time
# conversion. This is the one place that convention is defined; everything
# that writes or reasons about those columns should go through here rather
# than calling datetime.utcnow()/datetime.now() directly.
#
# Deliberately NOT used for JWT/OTP expiry timing (see app/utils/auth.py,
# app/services/otp_service.py) -- those compare a self-consistent pair of
# UTC instants and stay on datetime.utcnow(), since PyJWT's own expiry
# check assumes UTC and mixing conventions there risks real auth bugs.
IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    """Current wall-clock time in IST, as a naive datetime truncated to
    whole seconds -- stored rows should read HH:MM:SS, not fractional
    seconds."""
    return datetime.now(IST).replace(tzinfo=None, microsecond=0)


def to_ist_naive(dt: datetime) -> datetime:
    """Normalize an incoming datetime to naive IST wall-clock digits,
    truncated to whole seconds (see now_ist).

    If `dt` is offset-aware (e.g. parsed from an ISO string with a 'Z' or
    a Gmail/SMS timestamp), convert it to IST and drop the tzinfo. If it's
    already naive, it's assumed to already be IST -- the app never
    constructs naive datetimes in any other zone.
    """
    if dt.tzinfo is not None:
        dt = dt.astimezone(IST).replace(tzinfo=None)
    return dt.replace(microsecond=0)
