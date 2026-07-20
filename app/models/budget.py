from sqlalchemy import Column, String, Float, DateTime, ForeignKey, func
from app.config.database import Base
from datetime import datetime
import uuid

class Budget(Base):
    __tablename__ = "budgets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    category = Column(String, nullable=False)
    limit_amount = Column(Float, nullable=False)
    spent_amount = Column(Float, default=0)
    period = Column(String, nullable=False)  # weekly, monthly
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    def __repr__(self):
        return f"<Budget {self.category} {self.limit_amount}>"
