from typing import Optional

from pydantic import BaseModel

class MonthlyTotal(BaseModel):
    year: int
    month: int
    label: str
    total: float

class CategoryBreakdownItem(BaseModel):
    category: str
    total: float

class MerchantBreakdownItem(BaseModel):
    merchant: str
    total: float
    count: int

class AccountBreakdownItem(BaseModel):
    account_id: Optional[int]  # null = not linked to any account
    name: str
    type: Optional[str]
    total: float

class PaymentMethodBreakdownItem(BaseModel):
    payment_method: Optional[str]  # null = unknown (manual entries without one)
    total: float
    count: int

class InsightsSummary(BaseModel):
    monthly_totals: list[MonthlyTotal]
    monthly_income_totals: list[MonthlyTotal]
    category_breakdown: list[CategoryBreakdownItem]
    top_merchants: list[MerchantBreakdownItem]
    # This month's spend, split by account / card and by payment method —
    # what to compare against one bank's or one UPI app's own monthly total.
    account_breakdown: list[AccountBreakdownItem] = []
    payment_method_breakdown: list[PaymentMethodBreakdownItem] = []
