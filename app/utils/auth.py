from datetime import datetime, timedelta
from typing import Optional
import bcrypt
import jwt
import os
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.models.user import User

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    # No hardcoded fallback: a guessable default would let anyone forge
    # valid JWTs for any user if this ever got deployed without the env
    # var set, instead of failing loudly at startup.
    raise RuntimeError("SECRET_KEY environment variable must be set")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
PENDING_TOKEN_EXPIRE_MINUTES = int(os.getenv("OTP_EXPIRE_MINUTES", "5"))

security = HTTPBearer()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    # PyJWT enforces RFC 7519's "sub is a StringOrURI" rule and raises
    # InvalidSubjectError decoding a token whose sub isn't a string — every
    # caller here passes the integer user id, so it has to be stringified
    # before encoding (and parsed back to int wherever it's read below).
    if "sub" in to_encode:
        to_encode["sub"] = str(to_encode["sub"])
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> Optional[int]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        if sub is None:
            return None
        return int(sub)
    except (jwt.InvalidTokenError, ValueError):
        return None


def create_pending_token(user_id: int, purpose: str) -> str:
    """A short-lived token identifying a user who passed the password check but
    hasn't completed OTP verification yet — deliberately separate from a real
    access token so it can't be used to call authenticated routes."""
    return create_access_token(
        data={"sub": user_id, "purpose": purpose},
        expires_delta=timedelta(minutes=PENDING_TOKEN_EXPIRE_MINUTES)
    )


def decode_pending_token(token: str) -> Optional[dict]:
    """Like verify_pending_token, but doesn't require knowing the purpose up
    front — used by /resend-otp, which serves both the login and
    password-reset flows and just needs to reissue a code for whichever
    purpose the token was already scoped to. `sub` is parsed back to int
    here (see create_access_token) so every caller gets a real user id."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if not payload.get("sub") or not payload.get("purpose"):
            return None
        payload["sub"] = int(payload["sub"])
        return payload
    except (jwt.InvalidTokenError, ValueError):
        return None


def verify_pending_token(token: str, purpose: str) -> Optional[int]:
    payload = decode_pending_token(token)
    if not payload or payload.get("purpose") != purpose:
        return None
    return payload.get("sub")

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """FastAPI dependency: resolves the bearer token to the authenticated User, or 401s."""
    user_id = verify_token(credentials.credentials)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user
