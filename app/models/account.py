from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from app.config.database import Base
from app.utils.timezone import now_ist

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
    created_at = Column(DateTime, default=now_ist)
    updated_at = Column(DateTime, default=now_ist, onupdate=now_ist)

    def __repr__(self):
        return f"<Account {self.name} ({self.type})>"
