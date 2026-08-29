from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.services.exchange_rate_service import SUPPORTED_CURRENCIES

AccountType = Literal["bank", "cash", "credit_card", "wallet", "investment"]
SupportedCurrency = Literal[SUPPORTED_CURRENCIES]

# A ceiling, not a positivity constraint — a credit card can legitimately
# start with a negative opening_balance (an overpayment/credit), unlike a
# transaction amount which always has an explicit debit/credit direction.
MAX_OPENING_BALANCE = 100_000_000

class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    type: AccountType
    # Unconstrained on AccountResponse (below) so reading back a pre-existing
    # account with an unlisted currency never breaks — only creation is gated.
    currency: SupportedCurrency = "INR"
    opening_balance: float = Field(default=0, ge=-MAX_OPENING_BALANCE, le=MAX_OPENING_BALANCE)

class AccountUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    opening_balance: Optional[float] = Field(default=None, ge=-MAX_OPENING_BALANCE, le=MAX_OPENING_BALANCE)
    is_archived: Optional[bool] = None

class AccountResponse(BaseModel):
    id: int
    name: str
    type: AccountType
    currency: str
    opening_balance: float
    balance: float
    is_archived: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class NetWorthAccountItem(BaseModel):
    id: int
    name: str
    type: AccountType
    balance: float

class NetWorthSummary(BaseModel):
    net_worth: float
    total_assets: float
    total_liabilities: float
    accounts: list[NetWorthAccountItem]
