from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.money import Money

AccountType = Literal["bank", "cash", "credit_card", "wallet", "investment"]

# A ceiling, not a positivity constraint — a credit card can legitimately
# start with a negative opening_balance (an overpayment/credit), unlike a
# transaction amount which always has an explicit debit/credit direction.
MAX_OPENING_BALANCE = 100_000_000

class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    type: AccountType
    # The app is INR-only; kept as a field so the row/response shape doesn't change.
    currency: str = "INR"
    opening_balance: Money = Field(default=0, ge=-MAX_OPENING_BALANCE, le=MAX_OPENING_BALANCE)

class AccountUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    opening_balance: Optional[Money] = Field(default=None, ge=-MAX_OPENING_BALANCE, le=MAX_OPENING_BALANCE)
    is_archived: Optional[bool] = None

class AccountResponse(BaseModel):
    id: int
    name: str
    type: AccountType
    currency: str
    opening_balance: Money
    balance: Money
    is_archived: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class NetWorthAccountItem(BaseModel):
    id: int
    name: str
    type: AccountType
    balance: Money

class NetWorthSummary(BaseModel):
    net_worth: Money
    total_assets: Money
    total_liabilities: Money
    accounts: list[NetWorthAccountItem]
