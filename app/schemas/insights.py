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

class InsightsSummary(BaseModel):
    monthly_totals: list[MonthlyTotal]
    category_breakdown: list[CategoryBreakdownItem]
    top_merchants: list[MerchantBreakdownItem]
