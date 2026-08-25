import hmac
import os
from fastapi import Header, HTTPException, status

ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")


def require_admin_key(x_admin_key: str = Header(...)):
    """Gate for the /api/admin/* routes. Separate from user JWT auth since
    there's no is_admin concept on User yet — a single shared key, like the
    monitoring dashboard checking in, not a user session."""
    if not ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin monitoring is not configured (ADMIN_API_KEY unset)"
        )
    # Constant-time compare — this is a secret-vs-secret check, not a
    # lookup, so an early-exit `==` would leak how many leading bytes matched.
    if not hmac.compare_digest(x_admin_key, ADMIN_API_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")
