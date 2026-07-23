from datetime import datetime

from pydantic import BaseModel

class RecurringItem(BaseModel):
    merchant: str
    category: str
    average_amount: float
    cadence: str
    occurrences: int
    last_date: datetime
    next_due_date: datetime

class RecurringSummary(BaseModel):
    items: list[RecurringItem]
    monthly_total: float
