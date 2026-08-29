from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

CategoryType = str  # "expense" | "income" | "both" — validated with a pattern below, not a Literal, so old clients sending nothing still default cleanly

class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    icon: str = Field(default="📌", max_length=8)
    type: CategoryType = Field(default="expense", pattern="^(expense|income|both)$")

class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=40)
    icon: Optional[str] = Field(default=None, max_length=8)
    type: Optional[CategoryType] = Field(default=None, pattern="^(expense|income|both)$")

class CategoryResponse(BaseModel):
    id: int
    name: str
    icon: str
    type: CategoryType
    is_default: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
