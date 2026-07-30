from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

AccountType = Literal["bank", "cash", "credit_card", "wallet", "investment"]

class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    type: AccountType
    currency: str = "INR"
    opening_balance: float = 0

class AccountUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    opening_balance: Optional[float] = None
    is_archived: Optional[bool] = None

class AccountResponse(BaseModel):
    id: str
    name: str
    type: AccountType
    currency: str
    opening_balance: float
    balance: float
    is_archived: bool
    created_at: datetime

    class Config:
        from_attributes = True

class NetWorthAccountItem(BaseModel):
    id: str
    name: str
    type: AccountType
    balance: float

class NetWorthSummary(BaseModel):
    net_worth: float
    total_assets: float
    total_liabilities: float
    accounts: list[NetWorthAccountItem]
