from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from typing import Optional, Literal

from app.services.exchange_rate_service import SUPPORTED_CURRENCIES

TransactionType = Literal["debit", "credit"]
TransactionSource = Literal["gmail", "manual", "sms", "aa"]
SupportedCurrency = Literal[SUPPORTED_CURRENCIES]

# `type` (debit/credit) already carries direction, so amount is always a
# magnitude — zero/negative is nonsensical and would corrupt compute_balance/
# compute_spent. The upper bound is a defensive ceiling against a stray
# extra digit or a malicious value, not a real transaction limit.
MAX_TRANSACTION_AMOUNT = 100_000_000

class TransactionBase(BaseModel):
    # Left as plain str here (not SupportedCurrency) since TransactionResponse
    # inherits this class to serialize existing rows — constraining it would
    # break reading back any pre-existing transaction whose currency predates
    # this list. The input schemas below constrain it instead.
    amount: float = Field(gt=0, le=MAX_TRANSACTION_AMOUNT)
    currency: str
    type: TransactionType
    category: str
    merchant: str
    description: str
    date: datetime
    source: TransactionSource
    is_recurring: bool = False
    account_id: Optional[int] = None

class TransactionCreate(TransactionBase):
    currency: SupportedCurrency
    raw_text: Optional[str] = None

class TransactionUpdate(BaseModel):
    amount: Optional[float] = Field(default=None, gt=0, le=MAX_TRANSACTION_AMOUNT)
    currency: Optional[SupportedCurrency] = None
    type: Optional[TransactionType] = None
    category: Optional[str] = None
    merchant: Optional[str] = None
    description: Optional[str] = None
    account_id: Optional[int] = None

class TransactionResponse(TransactionBase):
    id: int
    user_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class TransactionList(BaseModel):
    transactions: list[TransactionResponse]
    total: int
    page: int
    limit: int
