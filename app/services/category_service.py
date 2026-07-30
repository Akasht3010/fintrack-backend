from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.budget import Budget
from app.models.category import Category
from app.models.transaction import Transaction


class DuplicateCategoryError(Exception):
    """Raised when a name collides (case-insensitive) with a default or the user's own category."""
    pass


class CategoryInUseError(Exception):
    """Raised when deleting a category still referenced by a transaction or budget."""
    pass


class CategoryService:
    @staticmethod
    def list_visible(db: Session, user_id: str) -> list[Category]:
        """Default categories plus this user's own, defaults first in their original order."""
        return (
            db.query(Category)
            .filter(or_(Category.user_id.is_(None), Category.user_id == user_id))
            .order_by(Category.sort_order.is_(None), Category.sort_order, Category.created_at)
            .all()
        )

    @staticmethod
    def name_exists(db: Session, user_id: str, name: str, exclude_id: str | None = None) -> bool:
        query = db.query(Category).filter(
            or_(Category.user_id.is_(None), Category.user_id == user_id),
            func.lower(Category.name) == name.lower()
        )
        if exclude_id:
            query = query.filter(Category.id != exclude_id)
        return db.query(query.exists()).scalar()

    @staticmethod
    def name_in_use(db: Session, user_id: str, name: str) -> bool:
        in_transactions = db.query(Transaction).filter(
            Transaction.user_id == user_id, Transaction.category == name
        ).first()
        if in_transactions:
            return True
        return db.query(Budget).filter(
            Budget.user_id == user_id, Budget.category == name
        ).first() is not None

    @staticmethod
    def create(db: Session, user_id: str, name: str, icon: str) -> Category:
        name = name.strip()
        if CategoryService.name_exists(db, user_id, name):
            raise DuplicateCategoryError()

        category = Category(user_id=user_id, name=name, icon=icon or "📌")
        db.add(category)
        db.commit()
        db.refresh(category)
        return category

    @staticmethod
    def get_own(db: Session, user_id: str, category_id: str) -> Category | None:
        """Only ever matches a category this user created — defaults (user_id NULL) are never editable/deletable."""
        return db.query(Category).filter(Category.id == category_id, Category.user_id == user_id).first()

    @staticmethod
    def update(db: Session, category: Category, name: str | None, icon: str | None) -> Category:
        if name is not None:
            name = name.strip()
            if CategoryService.name_exists(db, category.user_id, name, exclude_id=category.id):
                raise DuplicateCategoryError()

            old_name = category.name
            category.name = name
            if old_name != name:
                db.query(Transaction).filter(
                    Transaction.user_id == category.user_id, Transaction.category == old_name
                ).update({"category": name})
                db.query(Budget).filter(
                    Budget.user_id == category.user_id, Budget.category == old_name
                ).update({"category": name})

        if icon is not None:
            category.icon = icon

        db.commit()
        db.refresh(category)
        return category

    @staticmethod
    def delete(db: Session, category: Category) -> None:
        if CategoryService.name_in_use(db, category.user_id, category.name):
            raise CategoryInUseError()
        db.delete(category)
        db.commit()
