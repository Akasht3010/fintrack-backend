from sqlalchemy import Column, Integer, String, Boolean, DateTime, Index, text
from app.config.database import Base
from app.utils.timezone import now_ist

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    phone = Column(String, nullable=True)
    # Nullable: accounts created via Google sign-in have no password — they
    # authenticate via Google's own identity check instead of password+OTP.
    password_hash = Column(String, nullable=True)
    avatar = Column(String, nullable=True)
    google_id = Column(String, unique=True, nullable=True)
    gmail_connected = Column(Boolean, default=False)
    gmail_refresh_token = Column(String, nullable=True)
    created_at = Column(DateTime, default=now_ist)
    updated_at = Column(DateTime, default=now_ist, onupdate=now_ist)

    __table_args__ = (
        # `phone` is only checked for uniqueness in application code
        # (UserService.create_user) — a real DB constraint closes the race
        # where two concurrent signups with the same phone both pass that
        # check and create duplicate accounts sharing a number. Partial
        # (not plain unique=True on the column) because phone is nullable —
        # same pattern as transactions' (user_id, raw_text) dedup index.
        Index(
            'uq_users_phone',
            'phone',
            unique=True,
            postgresql_where=text('phone IS NOT NULL'),
            sqlite_where=text('phone IS NOT NULL'),
        ),
    )

    def __repr__(self):
        return f"<User {self.email}>"
