from sqlalchemy.orm import Session
from app.models.user import User
from app.schemas.user import UserCreate
import re
import uuid


def normalize_phone(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


class UserService:
    @staticmethod
    def get_user_by_email(db: Session, email: str) -> User:
        return db.query(User).filter(User.email == email).first()

    @staticmethod
    def get_user_by_phone(db: Session, phone: str) -> User:
        normalized = normalize_phone(phone)
        if not normalized:
            return None
        return db.query(User).filter(User.phone == normalized).first()

    @staticmethod
    def get_user_by_id(db: Session, user_id: str) -> User:
        return db.query(User).filter(User.id == user_id).first()

    @staticmethod
    def find_by_identifier(db: Session, identifier: str) -> User:
        """Look up a user by whichever identifier they logged in with (email or phone)."""
        identifier = (identifier or "").strip()
        if "@" in identifier:
            return UserService.get_user_by_email(db, identifier.lower())
        return UserService.get_user_by_phone(db, identifier)

    @staticmethod
    def create_user(db: Session, user_create: UserCreate) -> User:
        phone = normalize_phone(user_create.phone) if user_create.phone else None
        email = user_create.email.lower() if user_create.email else None

        if not email and not phone:
            raise ValueError("Either email or phone is required")

        # Check for an existing account by phone first, then email,
        # so the same person doesn't end up with duplicate accounts.
        existing = None
        if phone:
            existing = UserService.get_user_by_phone(db, phone)
        if not existing and email:
            existing = UserService.get_user_by_email(db, email)
        if existing:
            return existing

        if not email:
            email = f"user_{phone}@fintrack.app"

        db_user = User(
            id=str(uuid.uuid4()),
            name=user_create.name or "User",
            email=email,
            phone=phone,
            gmail_connected=False
        )
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user

    @staticmethod
    def update_gmail_token(db: Session, user_id: str, refresh_token: str) -> User:
        user = UserService.get_user_by_id(db, user_id)
        if user:
            user.gmail_connected = True
            user.gmail_refresh_token = refresh_token
            db.commit()
            db.refresh(user)
        return user
