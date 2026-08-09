from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.schemas.user import UserCreate, UserResponse
from app.services.user_service import UserService, DuplicateUserError, normalize_phone
from app.services.gmail_service import GmailService
from app.services.otp_service import issue_otp, verify_otp as verify_otp_code, OtpError
from app.utils.auth import (
    create_access_token,
    create_pending_token,
    decode_pending_token,
    verify_pending_token,
    verify_password,
    hash_password,
    get_current_user,
)
from app.models.user import User
from app.models.transaction import Transaction
from app.models.budget import Budget
from pydantic import BaseModel, EmailStr, field_validator, model_validator

router = APIRouter(prefix="/api/auth", tags=["auth"])
gmail_service = GmailService()

OTP_LOGIN_PURPOSE = "login"
OTP_PASSWORD_RESET_PURPOSE = "password_reset"


def _validate_password_strength(value: str) -> str:
    if len(value) < 8:
        raise ValueError("Password must be at least 8 characters")
    if len(value.encode("utf-8")) > 72:
        raise ValueError("Password must be at most 72 characters")
    return value


def _mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        masked = local[:1] + "*" * max(len(local) - 1, 1)
    else:
        masked = local[:2] + "*" * (len(local) - 2)
    return f"{masked}@{domain}"


class SignupRequest(BaseModel):
    name: str
    email: EmailStr
    phone: str
    password: str
    confirm_password: str

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        digits = normalize_phone(value)
        if len(digits) != 10:
            raise ValueError("Phone number must be 10 digits")
        return digits

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_password_strength(value)

    @model_validator(mode="after")
    def validate_passwords_match(self):
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self

class SignupResponse(BaseModel):
    access_token: str
    user: UserResponse

class LoginRequest(BaseModel):
    identifier: str  # phone number or email address
    password: str

class LoginPendingResponse(BaseModel):
    pending_token: str
    email_hint: str
    message: str = "Verification code sent"

class VerifyOtpRequest(BaseModel):
    pending_token: str
    code: str

class ResendOtpRequest(BaseModel):
    pending_token: str

class ForgotPasswordRequest(BaseModel):
    identifier: str  # phone number or email address

class ResetPasswordRequest(BaseModel):
    pending_token: str
    code: str
    new_password: str
    confirm_new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return _validate_password_strength(value)

    @model_validator(mode="after")
    def validate_passwords_match(self):
        if self.new_password != self.confirm_new_password:
            raise ValueError("Passwords do not match")
        return self

class LoginResponse(BaseModel):
    access_token: str
    user: UserResponse

class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        digits = normalize_phone(value)
        if len(digits) != 10:
            raise ValueError("Phone number must be 10 digits")
        return digits

@router.post("/signup", response_model=SignupResponse)
async def signup(request: SignupRequest, db: Session = Depends(get_db)):
    """Create a new user account. Fails if the email or phone is already registered."""
    user_create = UserCreate(
        name=request.name,
        email=request.email,
        phone=request.phone,
        password=request.password
    )

    try:
        user = UserService.create_user(db, user_create)
    except DuplicateUserError as e:
        detail = (
            "An account with this email already exists"
            if e.field == "email"
            else "An account with this phone number already exists"
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    access_token = create_access_token(data={"sub": user.id})

    return {
        "access_token": access_token,
        "user": user
    }

@router.post("/login", response_model=LoginPendingResponse)
async def login(request: LoginRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Step 1 of login: verify the password, then email a one-time code. Doesn't
    issue an access token yet — that only happens after /verify-otp succeeds."""
    identifier = request.identifier.strip()
    if not identifier:
        raise HTTPException(status_code=400, detail="Phone number or email is required")

    user = UserService.find_by_identifier(db, identifier)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account found for this phone number or email"
        )

    if not user.password_hash:
        detail = (
            "This account signs in with Google. Use \"Continue with Google\" instead."
            if user.google_id
            else "This account has no password set yet — sign up again or use \"Continue with Google\" to link it."
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    if not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect password")

    try:
        issue_otp(db, user, purpose=OTP_LOGIN_PURPOSE, background_tasks=background_tasks)
    except OtpError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    pending_token = create_pending_token(user.id, purpose=OTP_LOGIN_PURPOSE)

    return {
        "pending_token": pending_token,
        "email_hint": _mask_email(user.email)
    }


@router.post("/verify-otp", response_model=LoginResponse)
async def verify_otp_endpoint(request: VerifyOtpRequest, db: Session = Depends(get_db)):
    """Step 2 of login: check the emailed code and, on success, issue the real access token."""
    user_id = verify_pending_token(request.pending_token, purpose=OTP_LOGIN_PURPOSE)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Verification session expired. Please log in again.")

    user = UserService.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    try:
        verify_otp_code(db, user_id, request.code, purpose=OTP_LOGIN_PURPOSE)
    except OtpError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    access_token = create_access_token(data={"sub": user.id})

    return {
        "access_token": access_token,
        "user": user
    }


@router.post("/resend-otp")
async def resend_otp_endpoint(request: ResendOtpRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Shared by the login and password-reset flows — reissues a code for
    whichever purpose the pending token was already scoped to."""
    payload = decode_pending_token(request.pending_token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Verification session expired. Please start over.")

    user = UserService.get_user_by_id(db, payload["sub"])
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    try:
        issue_otp(db, user, purpose=payload["purpose"], background_tasks=background_tasks)
    except OtpError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    return {"message": "Verification code resent"}


@router.post("/forgot-password", response_model=LoginPendingResponse)
async def forgot_password(request: ForgotPasswordRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Step 1 of password reset: email an OTP to the account's registered
    address. Deliberately doesn't require an existing password — this also
    covers a Google-only account setting a password for the first time."""
    identifier = request.identifier.strip()
    if not identifier:
        raise HTTPException(status_code=400, detail="Phone number or email is required")

    user = UserService.find_by_identifier(db, identifier)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account found for this phone number or email"
        )

    try:
        issue_otp(db, user, purpose=OTP_PASSWORD_RESET_PURPOSE, background_tasks=background_tasks)
    except OtpError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    pending_token = create_pending_token(user.id, purpose=OTP_PASSWORD_RESET_PURPOSE)

    return {
        "pending_token": pending_token,
        "email_hint": _mask_email(user.email)
    }


@router.post("/reset-password", response_model=LoginResponse)
async def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Step 2 of password reset: check the emailed code, set the new password,
    and log the user straight in (the OTP already proved email ownership)."""
    user_id = verify_pending_token(request.pending_token, purpose=OTP_PASSWORD_RESET_PURPOSE)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Verification session expired. Please start over.")

    user = UserService.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    try:
        verify_otp_code(db, user_id, request.code, purpose=OTP_PASSWORD_RESET_PURPOSE)
    except OtpError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    user.password_hash = hash_password(request.new_password)
    db.commit()

    access_token = create_access_token(data={"sub": user.id})

    return {
        "access_token": access_token,
        "user": user
    }

@router.get("/me", response_model=UserResponse)
async def read_current_user(current_user: User = Depends(get_current_user)):
    """Get the authenticated user (identified by the bearer token)"""
    return current_user

@router.patch("/me", response_model=UserResponse)
async def update_current_user(
    request: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update the authenticated user's name/email/phone. Email and phone must stay unique."""
    updates = request.model_dump(exclude_unset=True, exclude_none=True)

    if "email" in updates:
        email = updates["email"].lower()
        existing = UserService.get_user_by_email(db, email)
        if existing and existing.id != current_user.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")
        updates["email"] = email

    if "phone" in updates:
        existing = UserService.get_user_by_phone(db, updates["phone"])
        if existing and existing.id != current_user.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this phone number already exists")

    for field, value in updates.items():
        setattr(current_user, field, value)

    db.commit()
    db.refresh(current_user)
    return current_user

@router.delete("/me")
async def delete_current_user(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Permanently delete the authenticated user's account and all their data. Irreversible."""
    if current_user.gmail_refresh_token:
        try:
            gmail_service.revoke_token(current_user.gmail_refresh_token)
        except Exception:
            pass

    db.query(Transaction).filter(Transaction.user_id == current_user.id).delete()
    db.query(Budget).filter(Budget.user_id == current_user.id).delete()
    db.delete(current_user)
    db.commit()

    return {"message": "Account deleted"}

@router.post("/refresh")
async def refresh_token(current_user: User = Depends(get_current_user)):
    """Issue a fresh access token for the authenticated user"""
    access_token = create_access_token(data={"sub": current_user.id})
    return {"access_token": access_token}
