import hmac
import os
from fastapi import Header, HTTPException, Request, status

from app.utils.rate_limit import limiter

ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")


# Applied to the dependency itself (not the route) so a wrong key is
# throttled before it ever reaches the route — a @limiter.limit() on the
# route function only runs once dependencies have already succeeded, which
# would let repeated wrong-key attempts through unthrottled.
@limiter.limit("30/minute")
def require_admin_key(request: Request, x_admin_key: str = Header(...)):
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
