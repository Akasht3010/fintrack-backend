from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, func, UniqueConstraint
from app.config.database import Base
import uuid

class Category(Base):
    __tablename__ = "categories"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)  # NULL = built-in default, visible to everyone
    name = Column(String, nullable=False)
    icon = Column(String, nullable=False, default="📌")
    sort_order = Column(Integer, nullable=True)  # only set on seeded defaults, to preserve their original order
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint('user_id', 'name', name='uq_user_category_name'),
    )

    @property
    def is_default(self) -> bool:
        return self.user_id is None

    def __repr__(self):
        return f"<Category {self.name}>"
