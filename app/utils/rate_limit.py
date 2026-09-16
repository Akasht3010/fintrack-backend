import os

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

limiter = Limiter(key_func=get_remote_address, enabled=RATE_LIMIT_ENABLED)
