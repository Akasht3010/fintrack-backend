from sqlalchemy import Column, String, Float, DateTime, Boolean, ForeignKey, func, Index, text
from app.config.database import Base
from datetime import datetime
import uuid

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True, index=True)
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
        # `raw_text` carries the per-source dedup marker (gmail:<id>,
        # sms:<address>:<date>) for imported transactions; manual ones leave
        # it null. Backed by a DB constraint (not just the app-level
        # check-then-insert in the sync endpoints) so two concurrent syncs
        # can't both slip past the check and double-import the same message.
        Index(
            'uq_transactions_user_raw_text',
            'user_id', 'raw_text',
            unique=True,
            postgresql_where=text('raw_text IS NOT NULL'),
            sqlite_where=text('raw_text IS NOT NULL'),
        ),
    )

    def __repr__(self):
        return f"<Transaction {self.merchant} {self.amount}>"
