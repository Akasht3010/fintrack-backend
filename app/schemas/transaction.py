from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Literal

TransactionType = Literal["debit", "credit"]
TransactionCategory = Literal[
    "food", "transport", "shopping", "entertainment", 
    "health", "utilities", "rent", "subscriptions", "transfer", "other"
]
TransactionSource = Literal["gmail", "manual", "sms", "aa"]

class TransactionBase(BaseModel):
    amount: float
    currency: str
    type: TransactionType
    category: TransactionCategory
    merchant: str
    description: str
    date: datetime
    source: TransactionSource
    is_recurring: bool = False

class TransactionCreate(TransactionBase):
    raw_text: Optional[str] = None

class TransactionUpdate(BaseModel):
    amount: Optional[float] = None
    type: Optional[TransactionType] = None
    category: Optional[TransactionCategory] = None
    merchant: Optional[str] = None
    description: Optional[str] = None

class TransactionResponse(TransactionBase):
    id: str
    user_id: str
    created_at: datetime

    class Config:
        from_attributes = True

class TransactionList(BaseModel):
    transactions: list[TransactionResponse]
    total: int
    page: int
    limit: int
