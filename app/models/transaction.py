from sqlalchemy import Column, Integer, String, Numeric, DateTime, Boolean, ForeignKey, Index, text
from app.config.database import Base
from app.utils.timezone import now_ist

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    # NUMERIC, not FLOAT: money must be exact, not the nearest representable
    # binary fraction — a FLOAT column here would let rounding drift creep
    # into SUM()s (balances, budget spend) the more transactions accumulate.
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String, default="INR")
    type = Column(String, nullable=False)  # debit, credit
    category = Column(String, nullable=False)
    merchant = Column(String, nullable=False)
    description = Column(String, nullable=False)
    date = Column(DateTime, nullable=False, index=True)
    source = Column(String, nullable=False)  # gmail, manual, sms, aa
    raw_text = Column(String, nullable=True)
    # Client-generated, opt-in dedup key for manual entry — raw_text already
    # plays this role for the gmail/sms import paths, but those build the
    # marker themselves server-side; a manual POST has no equivalent, so a
    # retried request (e.g. a mobile client resending after a timeout, the
    # first attempt having actually succeeded) isn't caught by anything.
    idempotency_key = Column(String, nullable=True)
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
        Index(
            'uq_transactions_user_idempotency_key',
            'user_id', 'idempotency_key',
            unique=True,
            postgresql_where=text('idempotency_key IS NOT NULL'),
            sqlite_where=text('idempotency_key IS NOT NULL'),
        ),
    )

    def __repr__(self):
        return f"<Transaction {self.merchant} {self.amount}>"
