from pydantic import BaseModel, ConfigDict, Field, model_validator
from datetime import datetime
from typing import Optional, Literal

from app.schemas.money import Money

TransactionType = Literal["debit", "credit"]
TransactionSource = Literal["gmail", "manual", "sms", "aa", "statement"]
# How the money moved. Imports get it from the alert text; "other" is an
# import whose alert didn't say.
PaymentMethod = Literal["upi", "card", "netbanking", "atm", "autopay", "cash", "other"]

# `type` (debit/credit) already carries direction, so amount is always a
# magnitude — zero/negative is nonsensical and would corrupt compute_balance/
# compute_spent. The upper bound is a defensive ceiling against a stray
# extra digit or a malicious value, not a real transaction limit.
MAX_TRANSACTION_AMOUNT = 100_000_000

# Text bounds: generous for real merchant names/notes, but no unbounded
# strings (the DB columns are unbounded VARCHAR).
MAX_CATEGORY_LENGTH = 60
MAX_MERCHANT_LENGTH = 120
MAX_DESCRIPTION_LENGTH = 500

class TransactionBase(BaseModel):
    # The app is INR-only. `currency` is kept on the row (and echoed back
    # here) purely so existing data stays valid; it's always "INR".
    amount: Money = Field(gt=0, le=MAX_TRANSACTION_AMOUNT)
    currency: str = "INR"
    type: TransactionType
    category: str = Field(min_length=1, max_length=MAX_CATEGORY_LENGTH)
    merchant: str = Field(min_length=1, max_length=MAX_MERCHANT_LENGTH)
    description: str = Field(max_length=MAX_DESCRIPTION_LENGTH)
    date: datetime
    source: TransactionSource
    is_recurring: bool = False
    account_id: Optional[int] = None
    payment_method: Optional[PaymentMethod] = None

class TransactionCreate(TransactionBase):
    # No raw_text: that column holds the Gmail/SMS import markers
    # ("gmail:<id>", "sms:<addr>:<ts>"), built server-side. Accepting it
    # here let a client claim a marker in advance and permanently block the
    # matching import via the (user_id, raw_text) unique index. An old
    # client still sending it is fine — unknown fields are ignored.
    #
    # Optional client-generated dedup key so a retried create (e.g. a mobile
    # client resending after a timeout) can't double-insert — enforced by a
    # DB unique index the same way raw_text is for imported transactions.
    idempotency_key: Optional[str] = Field(default=None, max_length=100)

class TransactionUpdate(BaseModel):
    amount: Optional[Money] = Field(default=None, gt=0, le=MAX_TRANSACTION_AMOUNT)
    type: Optional[TransactionType] = None
    category: Optional[str] = Field(default=None, min_length=1, max_length=MAX_CATEGORY_LENGTH)
    merchant: Optional[str] = Field(default=None, min_length=1, max_length=MAX_MERCHANT_LENGTH)
    description: Optional[str] = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    # May be explicitly cleared (unlink from an account / unknown method).
    account_id: Optional[int] = None
    payment_method: Optional[PaymentMethod] = None

    @model_validator(mode="after")
    def reject_null_for_required_columns(self):
        # Optional here only means "may be omitted". An explicit null for a
        # NOT NULL column used to reach the DB and come back as a 500.
        nulled = [
            name for name in ("amount", "type", "category", "merchant", "description")
            if name in self.model_fields_set and getattr(self, name) is None
        ]
        if nulled:
            raise ValueError(f"{', '.join(nulled)} cannot be null")
        return self

class TransactionResponse(TransactionBase):
    id: int
    user_id: int
    created_at: datetime
    # Trailing account/card digits the bank alert quoted (comma-separated),
    # so the app can offer to link an import no account claimed.
    account_hint: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class TransactionList(BaseModel):
    transactions: list[TransactionResponse]
    total: int
    page: int
    limit: int
