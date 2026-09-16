from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from typing import Literal

from app.schemas.money import Money

class BudgetBase(BaseModel):
    category: str
    limit_amount: Money = Field(gt=0)
    period: Literal["weekly", "monthly"]

class BudgetCreate(BudgetBase):
    pass

class BudgetUpdate(BaseModel):
    limit_amount: Money = Field(gt=0)

class BudgetResponse(BudgetBase):
    id: int
    user_id: int
    spent_amount: Money
    remaining_amount: Money
    start_date: datetime
    end_date: datetime

    model_config = ConfigDict(from_attributes=True)
