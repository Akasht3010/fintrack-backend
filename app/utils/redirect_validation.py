import os
from urllib.parse import urlparse

from fastapi import HTTPException, status

# Mirrors oauth_state.create_state's own threat model one step earlier: that
# nonce stops `state` from being forgeable, but app_redirect_uri itself used
# to be taken from the query string with no validation at all and baked
# straight into the nonce's payload — so /callback would hand a freshly
# minted token-exchange code to *any* host an attacker put in the link, not
# just the real app. This is the allowlist that closes that gap.

_ENV = os.getenv("ENV", "development")


def _allowed_web_origins() -> set[str]:
    return {o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()}


def validate_app_redirect_uri(uri: str, callback_path: str) -> None:
    """Only ever bind a destination this app actually controls into OAuth
    state. Three shapes are legitimate for a given callback_path (e.g.
    "auth-callback", "gmail-callback"):

    - the native app's fixed custom scheme (`fintrack://<callback_path>`)
    - an Expo Go dev-client redirect (`exp://<lan-ip-or-tunnel>/--/<callback_path>`)
      — the host varies every session, so this is allowed by shape only,
      and only outside production, where an attacker able to set ENV on
      the server would have bigger problems than this
    - one of the backend's own trusted web origins — CORS_ORIGINS already
      is that list (browser origins this backend trusts to call it
      cross-origin), so it doubles as the web redirect allowlist

    Anything else (attacker.example, javascript:, a bare IP, ...) is rejected.
    """
    if uri == f"fintrack://{callback_path}":
        return

    if _ENV != "production" and uri.startswith("exp://") and uri.endswith(f"/{callback_path}"):
        return

    parsed = urlparse(uri)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if parsed.scheme == "https" and parsed.path == f"/{callback_path}" and origin in _allowed_web_origins():
        return

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid redirect")
