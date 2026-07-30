from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    icon: str = Field(default="📌", max_length=8)

class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=40)
    icon: Optional[str] = Field(default=None, max_length=8)

class CategoryResponse(BaseModel):
    id: str
    name: str
    icon: str
    is_default: bool
    created_at: datetime

    class Config:
        from_attributes = True
