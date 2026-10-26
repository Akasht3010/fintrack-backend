from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel

from app.schemas.money import Money

# Largest statement upload accepted — a year of busy HDFC history as
# Delimited text is well under 1 MB; Excel roughly doubles that.
MAX_STATEMENT_BYTES = 5 * 1024 * 1024


class StatementMismatchItem(BaseModel):
    id: int
    date: datetime
    merchant: str
    amount: Money
    type: Literal["debit", "credit"]


class StatementImportResponse(BaseModel):
    bank: str
    account_last4: Optional[str]
    period_start: date
    period_end: date
    rows: int
    matched: int  # already in the app (from alerts / manual entry) — linked, not duplicated
    already_imported: int  # from an earlier upload of an overlapping statement
    added: int  # on the statement but missing from the app — now added
    added_debit_total: Money
    closing_balance: Optional[Money]
    balance_updated: bool
    # In the app for this account and period, but not on the statement.
    not_in_statement: list[StatementMismatchItem]
