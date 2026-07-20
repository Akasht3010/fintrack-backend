from pydantic import BaseModel
from datetime import datetime
from typing import Literal

class BudgetBase(BaseModel):
    category: str
    limit_amount: float
    period: Literal["weekly", "monthly"]

class BudgetCreate(BudgetBase):
    user_id: str

class BudgetResponse(BudgetBase):
    id: str
    user_id: str
    spent_amount: float
    start_date: datetime
    end_date: datetime

    class Config:
        from_attributes = True
