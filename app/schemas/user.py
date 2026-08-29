from pydantic import BaseModel, ConfigDict, EmailStr
from datetime import datetime
from typing import Optional

class UserBase(BaseModel):
    name: str
    email: EmailStr
    phone: str

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None

class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str] = None
    gmail_connected: bool
    avatar: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
