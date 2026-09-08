from sqlalchemy import Column, Computed, Integer, String, Float, DateTime, ForeignKey
from app.config.database import Base
from app.utils.timezone import now_ist

class Budget(Base):
    __tablename__ = "budgets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    category = Column(String, nullable=False)
    limit_amount = Column(Float, nullable=False)
    spent_amount = Column(Float, default=0)
    # Always limit_amount - spent_amount. A DB-generated column rather than a
    # third value the app has to keep in sync: the database recomputes it on
    # every write and it can never drift. Read-only from the ORM's side.
    remaining_amount = Column(Float, Computed("limit_amount - spent_amount", persisted=True))
    period = Column(String, nullable=False)  # weekly, monthly
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=now_ist)

    def __repr__(self):
        return f"<Budget {self.category} {self.limit_amount}>"
