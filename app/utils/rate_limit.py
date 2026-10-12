import os

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

# In-memory, per-process counters keyed by client IP — good enough for the
# single-instance Cloud Run deploy this app runs on today (see README). It
# won't hold a shared limit across multiple instances if this ever scales
# out; a Redis-backed storage_uri would be the next step then.
#
# Disabled by default under pytest (RATE_LIMIT_ENABLED=false in
# tests/conftest.py) so the test suite's many back-to-back /login and
# /forgot-password calls from a single fake client IP don't trip it.
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() != "false"

# How many proxies in front of this app append to X-Forwarded-For (1 on
# Cloud Run: Google's front end appends the connecting client's IP). Without
# it, request.client.host is the front end's own address, so every user
# lands in one shared bucket — a handful of logins would 429 everyone.
# Counted from the right because everything to the left of the hops we
# trust is whatever the client chose to send, and keying on that would let
# anyone dodge the limit by rotating the header. 0 (the default, for local
# dev and tests) ignores the header entirely.
TRUSTED_PROXY_HOPS = int(os.getenv("TRUSTED_PROXY_HOPS", "0"))


def client_ip(request: Request) -> str:
    if TRUSTED_PROXY_HOPS > 0:
        hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
        if len(hops) >= TRUSTED_PROXY_HOPS:
            return hops[-TRUSTED_PROXY_HOPS]
    return get_remote_address(request)


limiter = Limiter(key_func=client_ip, enabled=RATE_LIMIT_ENABLED)
