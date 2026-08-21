from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Index, text
from app.config.database import Base
from app.utils.timezone import now_ist

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
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
    created_at = Column(DateTime, default=now_ist)
    updated_at = Column(DateTime, default=now_ist, onupdate=now_ist)

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
