from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, func
from app.config.database import Base
import uuid


class OtpCode(Base):
    __tablename__ = "otp_codes"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    purpose = Column(String, nullable=False, default="login")
    code_hash = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    consumed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
