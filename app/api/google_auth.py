import os
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from app.config.database import get_db
from app.services.user_service import UserService
from app.utils.auth import create_access_token

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
    per-session) deep link as `app_redirect_uri`; we thread it through
    Google's `state` param so /callback knows where to send the user back
    afterwards, since the app's URL isn't something Google can be told about
    ahead of time (it changes every Expo Go session).
    """
    _require_configured()

    flow = _build_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=app_redirect_uri
    )
    return RedirectResponse(auth_url)


@router.get("/callback")
async def google_callback(code: str, state: str, db: Session = Depends(get_db)):
    """
    Google redirects here after consent (this URL must be registered in
    Google Cloud Console as an authorized redirect URI). We exchange the
    code server-side, verify the identity token, find-or-create the user,
    mint our own JWT, and bounce the browser back to the app's deep link
    (captured earlier in `state`) with that token attached.
    """
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

    separator = "&" if "?" in state else "?"
    return RedirectResponse(f"{state}{separator}token={access_token}")
