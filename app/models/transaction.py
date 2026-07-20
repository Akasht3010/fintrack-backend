from sqlalchemy import Column, String, Float, DateTime, Boolean, ForeignKey, func, Index
from app.config.database import Base
from datetime import datetime
import uuid

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="INR")
    type = Column(String, nullable=False)  # debit, credit
    category = Column(String, nullable=False)
    merchant = Column(String, nullable=False)
    description = Column(String, nullable=False)
    date = Column(DateTime, nullable=False, index=True)
    source = Column(String, nullable=False)  # gmail, manual, sms, aa
    raw_text = Column(String, nullable=True)
    is_recurring = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('idx_user_date', 'user_id', 'date'),
    )

    def __repr__(self):
        return f"<Transaction {self.merchant} {self.amount}>"
