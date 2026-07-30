from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal

class BudgetBase(BaseModel):
    category: str
    limit_amount: float = Field(gt=0)
    period: Literal["weekly", "monthly"]

class BudgetCreate(BudgetBase):
    pass

class BudgetUpdate(BaseModel):
    limit_amount: float = Field(gt=0)

class BudgetResponse(BudgetBase):
    id: str
    user_id: str
    spent_amount: float
    start_date: datetime
    end_date: datetime

    class Config:
        from_attributes = True
