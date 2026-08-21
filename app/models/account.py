from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, func
from app.config.database import Base

# Accounts whose balance represents money owed rather than money held —
# subtracted (not added) when computing net worth.
LIABILITY_TYPES = {"credit_card"}

class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)  # bank, cash, credit_card, wallet, investment
    currency = Column(String, default="INR")
    opening_balance = Column(Float, nullable=False, default=0)
    is_archived = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<Account {self.name} ({self.type})>"
