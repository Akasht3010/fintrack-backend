from pydantic import BaseModel


class DbHealth(BaseModel):
    status: str
    latency_ms: float


class DependencyCheck(BaseModel):
    ok: bool | None
    checked_at: float | None
    error: str | None


class Dependencies(BaseModel):
    smtp: DependencyCheck
    fx_rate_api: DependencyCheck


class HealthResponse(BaseModel):
    status: str
    uptime_seconds: float
    db: DbHealth
    version: str
    db_size_bytes: int | None
    dependencies: Dependencies


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


class OtpFunnel(BaseModel):
    issued_7d: int
    consumed_7d: int
    expired_7d: int


class TopCategory(BaseModel):
    category: str
    count: int
    total_amount: float


class StatsResponse(BaseModel):
    users: UserStats
    transactions: TransactionStats
    accounts_total: int
    budgets_total: int
    budget_adoption_pct: float
    otp: OtpFunnel
    gmail_stale_connections: int
    top_categories: list[TopCategory]
    signups_by_day: list[DayCount]
    transactions_by_day: list[DayCount]
