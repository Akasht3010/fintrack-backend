from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.money import Money

AccountType = Literal["bank", "cash", "credit_card", "wallet", "investment"]

# A ceiling, not a positivity constraint — a credit card can legitimately
# start with a negative opening_balance (an overpayment/credit), unlike a
# transaction amount which always has an explicit debit/credit direction.
MAX_OPENING_BALANCE = 100_000_000

# The trailing digits bank alerts print for an account or card.
LAST4_PATTERN = r"^\d{3,4}$"

class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    type: AccountType
    # The app is INR-only; kept as a field so the row/response shape doesn't change.
    currency: str = "INR"
    opening_balance: Money = Field(default=0, ge=-MAX_OPENING_BALANCE, le=MAX_OPENING_BALANCE)
    institution: Optional[str] = Field(default=None, max_length=60)
    last4: Optional[str] = Field(default=None, pattern=LAST4_PATTERN)
    card_last4: Optional[str] = Field(default=None, pattern=LAST4_PATTERN)

class AccountUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    opening_balance: Optional[Money] = Field(default=None, ge=-MAX_OPENING_BALANCE, le=MAX_OPENING_BALANCE)
    is_archived: Optional[bool] = None
    institution: Optional[str] = Field(default=None, max_length=60)
    last4: Optional[str] = Field(default=None, pattern=LAST4_PATTERN)
    card_last4: Optional[str] = Field(default=None, pattern=LAST4_PATTERN)

class AccountBalanceUpdate(BaseModel):
    """The balance the bank / UPI app shows, as of `as_of` (default: now)."""
    balance: Money = Field(ge=-MAX_OPENING_BALANCE, le=MAX_OPENING_BALANCE)
    as_of: Optional[datetime] = None

class AccountResponse(BaseModel):
    id: int
    name: str
    type: AccountType
    currency: str
    opening_balance: Money
    balance: Money
    is_archived: bool
    created_at: datetime
    institution: Optional[str] = None
    last4: Optional[str] = None
    card_last4: Optional[str] = None
    # Where the balance comes from: "alert" (the bank's last "Avl Bal"),
    # "manual" (typed in by the user), "statement" (an imported statement's
    # closing balance), or null (opening balance + transactions).
    balance_source: Optional[Literal["alert", "manual", "statement"]] = None
    balance_as_of: Optional[datetime] = None
    # False until the bank (an alert) or the user has supplied a real figure.
    balance_known: bool = True
    # Newest bank alert matched to this account — it's "verified" once set.
    last_alert_at: Optional[datetime] = None

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
