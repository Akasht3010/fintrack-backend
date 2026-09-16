import os

# Google returns scopes as full canonical URIs (e.g. .../auth/userinfo.email)
# even when requested by their short names (email, profile) — oauthlib treats
# that as a scope mismatch and raises unless told to relax. Must be set before
# any oauthlib token parsing happens.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from app.config.database import get_db
from app.services.user_service import UserService
from app.utils.auth import create_access_token
from app.utils.oauth_state import create_state, consume_state

router = APIRouter(prefix="/api/auth/google", tags=["google-auth"])

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
CALLBACK_PATH = "/api/auth/google/callback"
SCOPES = ["openid", "email", "profile"]


def _require_configured():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Google OAuth is not configured on the server")


def _build_flow() -> Flow:
    client_config = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    return Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=f"{PUBLIC_BASE_URL}{CALLBACK_PATH}"
    )


@router.get("/authorize")
async def google_authorize(app_redirect_uri: str = Query(...)):
    """
    Kicks off Google's OAuth consent flow. The app passes its own (dynamic,
    per-session) deep link as `app_redirect_uri`; rather than sending that
    straight to Google as `state` (client-controlled and forgeable — an
    attacker could substitute their own redirect and have our callback
    hand them a freshly-minted JWT for whoever completes consent), we mint
    a random nonce bound server-side to it and send only the nonce.
    """
    _require_configured()

    state = create_state({"app_redirect_uri": app_redirect_uri})
    flow = _build_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=state
    )
    return RedirectResponse(auth_url)


@router.get("/callback")
async def google_callback(code: str, state: str, db: Session = Depends(get_db)):
    """
    Google redirects here after consent (this URL must be registered in
    Google Cloud Console as an authorized redirect URI). We exchange the
    code server-side, verify the identity token, find-or-create the user,
    mint our own JWT, and bounce the browser back to the app's deep link
    (recovered from the nonce `/authorize` created) with that token attached.
    """
    pending = consume_state(state)
    if pending is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    app_redirect_uri = pending["app_redirect_uri"]

    _require_configured()
    flow = _build_flow()
    flow.fetch_token(code=code)
    credentials = flow.credentials

    idinfo = google_id_token.verify_oauth2_token(
        credentials.id_token,
        google_requests.Request(),
        GOOGLE_CLIENT_ID
    )

    user = UserService.find_or_create_google_user(
        db,
        email=idinfo["email"],
        name=idinfo.get("name") or idinfo["email"],
        avatar=idinfo.get("picture"),
        google_id=idinfo["sub"]
    )

    access_token = create_access_token(data={"sub": user.id})

    # The real JWT never goes in this redirect URL — a URL is exactly where
    # a bearer token ends up in web server access logs, any reverse proxy in
    # front of this service, and (on web) the browser's own history. Instead
    # a short-lived, single-use exchange code goes in the URL, and the app
    # trades it for the real token via POST /exchange once it lands on its
    # deep link.
    exchange_code = create_state({"access_token": access_token})

    separator = "&" if "?" in app_redirect_uri else "?"
    return RedirectResponse(f"{app_redirect_uri}{separator}code={exchange_code}")


class ExchangeRequest(BaseModel):
    code: str


class ExchangeResponse(BaseModel):
    access_token: str


@router.post("/exchange", response_model=ExchangeResponse)
async def google_exchange(request: ExchangeRequest):
    """Trades the one-time code from the /callback redirect for the real
    access token — see the comment in /callback for why the JWT itself
    doesn't travel in that redirect's URL. Single-use: a replayed code fails
    the same as an expired one."""
    pending = consume_state(request.code)
    if pending is None or "access_token" not in pending:
        raise HTTPException(status_code=401, detail="Invalid or expired code")
    return {"access_token": pending["access_token"]}
