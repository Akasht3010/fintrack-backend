from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.schemas.user import UserCreate, UserResponse
from app.services.user_service import UserService
from app.utils.auth import create_access_token
from pydantic import BaseModel, EmailStr
from typing import Optional

router = APIRouter(prefix="/api/auth", tags=["auth"])

class SignupRequest(BaseModel):
    name: Optional[str] = "User"
    email: Optional[EmailStr] = None
    phone: Optional[str] = None

class SignupResponse(BaseModel):
    access_token: str
    user: UserResponse

class LoginRequest(BaseModel):
    identifier: str  # phone number or email address

class LoginResponse(BaseModel):
    access_token: str
    user: UserResponse

@router.post("/signup", response_model=SignupResponse)
async def signup(request: SignupRequest, db: Session = Depends(get_db)):
    """Create a new user account (idempotent: returns the existing account if this phone/email is already registered)"""
    if not request.email and not request.phone:
        raise HTTPException(status_code=400, detail="Email or phone is required")

    user_create = UserCreate(
        name=request.name or "User",
        email=request.email,
        phone=request.phone
    )

    user = UserService.create_user(db, user_create)

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
async def get_current_user(user_id: str, db: Session = Depends(get_db)):
    """Get current authenticated user"""
    user = UserService.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user

@router.post("/refresh")
async def refresh_token(user_id: str):
    """Refresh access token"""
    access_token = create_access_token(data={"sub": user_id})
    return {"access_token": access_token}
