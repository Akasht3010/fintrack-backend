from sqlalchemy import Column, Integer, String, Numeric, Boolean, DateTime, ForeignKey
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
    # NUMERIC, not FLOAT — see the same note on Transaction.amount.
    opening_balance = Column(Numeric(12, 2), nullable=False, default=0)
    institution = Column(String, nullable=True)  # bank / issuer name, display only
    # Trailing digits of the account number (or the card number, for a
    # credit card) and of a bank account's debit card — what bank alerts
    # print ("A/c XX1234", "Card ending 9876"), so imports can be matched to
    # the right account.
    last4 = Column(String, nullable=True)
    card_last4 = Column(String, nullable=True)
    # The balance the bank last reported (an alert's "Avl Bal", or a figure
    # the user typed in from their bank / UPI app) and when. Once set it
    # anchors the balance: anchor + transactions after it, instead of
    # opening_balance + every transaction ever — so a missed or duplicated
    # import before the anchor can no longer skew it.
    reported_balance = Column(Numeric(12, 2), nullable=True)
    reported_balance_at = Column(DateTime, nullable=True)
    reported_balance_source = Column(String, nullable=True)  # alert | manual | statement
    is_archived = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now_ist)
    updated_at = Column(DateTime, default=now_ist, onupdate=now_ist)

    def __repr__(self):
        return f"<Account {self.name} ({self.type})>"
