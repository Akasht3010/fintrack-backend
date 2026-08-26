from pydantic import BaseModel


class DbHealth(BaseModel):
    status: str
    latency_ms: float


class HealthResponse(BaseModel):
    status: str
    uptime_seconds: float
    db: DbHealth


class DayCount(BaseModel):
    date: str
    count: int


class UserStats(BaseModel):
    total: int
    new_today: int
    new_7d: int
    new_30d: int
    gmail_connected: int
    active_7d: int
    dead_signups: int


class TransactionStats(BaseModel):
    total: int
    today: int
    by_source: dict[str, int]


class StatsResponse(BaseModel):
    users: UserStats
    transactions: TransactionStats
    accounts_total: int
    budgets_total: int
    signups_by_day: list[DayCount]
    transactions_by_day: list[DayCount]
