from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from typing import Optional, Literal

TransactionType = Literal["debit", "credit"]
TransactionSource = Literal["gmail", "manual", "sms", "aa"]

# `type` (debit/credit) already carries direction, so amount is always a
# magnitude — zero/negative is nonsensical and would corrupt compute_balance/
# compute_spent. The upper bound is a defensive ceiling against a stray
# extra digit or a malicious value, not a real transaction limit.
MAX_TRANSACTION_AMOUNT = 100_000_000

class TransactionBase(BaseModel):
    # The app is INR-only. `currency` is kept on the row (and echoed back
    # here) purely so existing data stays valid; it's always "INR".
    amount: float = Field(gt=0, le=MAX_TRANSACTION_AMOUNT)
    currency: str = "INR"
    type: TransactionType
    category: str
    merchant: str
    description: str
    date: datetime
    source: TransactionSource
    is_recurring: bool = False
    account_id: Optional[int] = None

class TransactionCreate(TransactionBase):
    raw_text: Optional[str] = None

class TransactionUpdate(BaseModel):
    amount: Optional[float] = Field(default=None, gt=0, le=MAX_TRANSACTION_AMOUNT)
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
