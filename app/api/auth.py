from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.schemas.user import UserCreate, UserResponse
from app.services.user_service import UserService, DuplicateUserError, normalize_phone
from app.utils.auth import create_access_token, get_current_user
from app.models.user import User
from pydantic import BaseModel, EmailStr, field_validator

router = APIRouter(prefix="/api/auth", tags=["auth"])

class SignupRequest(BaseModel):
    name: str
    email: EmailStr
    phone: str

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        digits = normalize_phone(value)
        if len(digits) != 10:
            raise ValueError("Phone number must be 10 digits")
        return digits

class SignupResponse(BaseModel):
    access_token: str
    user: UserResponse

class LoginRequest(BaseModel):
    identifier: str  # phone number or email address

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
        phone=request.phone
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

@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """Log in with a phone number or email address"""
    identifier = request.identifier.strip()
    if not identifier:
        raise HTTPException(status_code=400, detail="Phone number or email is required")

    user = UserService.find_by_identifier(db, identifier)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account found for this phone number or email"
        )

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

@router.post("/refresh")
async def refresh_token(current_user: User = Depends(get_current_user)):
    """Issue a fresh access token for the authenticated user"""
    access_token = create_access_token(data={"sub": current_user.id})
    return {"access_token": access_token}
