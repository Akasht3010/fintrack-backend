from sqlalchemy import Column, Integer, String, Boolean, DateTime
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

    def __repr__(self):
        return f"<User {self.email}>"
