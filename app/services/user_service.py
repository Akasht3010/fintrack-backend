from sqlalchemy.orm import Session
from app.models.user import User
from app.schemas.user import UserCreate
import re
import uuid


def normalize_phone(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


class DuplicateUserError(Exception):
    """Raised on signup when the email or phone is already registered to another account."""
    def __init__(self, field: str):
        self.field = field  # "email" or "phone"


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
        """Create a new user. Raises DuplicateUserError if the email or phone is already taken."""
        phone = normalize_phone(user_create.phone)
        email = user_create.email.lower()

        if UserService.get_user_by_email(db, email):
            raise DuplicateUserError("email")

        if UserService.get_user_by_phone(db, phone):
            raise DuplicateUserError("phone")

        db_user = User(
            id=str(uuid.uuid4()),
            name=user_create.name,
            email=email,
            phone=phone,
            gmail_connected=False
        )
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user

    @staticmethod
    def find_or_create_google_user(db: Session, email: str, name: str, avatar: str, google_id: str) -> User:
        """
        Google is treated as an identity verifier for the same account space as
        phone/email — a Google sign-in links to (or creates) the account with
        that email rather than being a separate identity.
        """
        email = email.lower()
        user = UserService.get_user_by_email(db, email)

        if user:
            changed = False
            if not user.google_id:
                user.google_id = google_id
                changed = True
            if avatar and user.avatar != avatar:
                user.avatar = avatar
                changed = True
            if changed:
                db.commit()
                db.refresh(user)
            return user

        db_user = User(
            id=str(uuid.uuid4()),
            name=name,
            email=email,
            phone=None,
            avatar=avatar,
            google_id=google_id,
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
