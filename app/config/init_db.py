from app.config.database import Base, engine, SessionLocal
from app.models.user import User
from app.models.transaction import Transaction
from app.models.budget import Budget
from app.models.category import Category
from app.models.account import Account
from sqlalchemy import inspect, text

# Order matches the categories this app shipped with before custom
# categories existed — preserved via sort_order so existing pickers/filters
# don't reshuffle for users upgrading in place.
DEFAULT_CATEGORIES = [
    ("food", "🍔"),
    ("transport", "🚗"),
    ("shopping", "🛍️"),
    ("entertainment", "🎬"),
    ("health", "🏥"),
    ("utilities", "💡"),
    ("rent", "🏠"),
    ("subscriptions", "🔄"),
    ("transfer", "💸"),
    ("other", "📌"),
]

def seed_default_categories():
    db = SessionLocal()
    try:
        existing_names = {
            name for (name,) in db.query(Category.name).filter(Category.user_id.is_(None)).all()
        }
        for order, (name, icon) in enumerate(DEFAULT_CATEGORIES):
            if name in existing_names:
                continue
            db.add(Category(user_id=None, name=name, icon=icon, sort_order=order))
        db.commit()
    finally:
        db.close()

def migrate_schema():
    """
    Base.metadata.create_all only creates missing tables — it never alters
    a table that already exists. `transactions` predates the accounts
    feature, so on an existing DB the new account_id column has to be added
    by hand. No FK constraint here (SQLite can't add one via ALTER TABLE
    anyway); ownership is enforced in the service layer instead, same as
    the string-based category field already is.
    """
    inspector = inspect(engine)
    if "transactions" not in inspector.get_table_names():
        return  # fresh DB — create_all above already built the right shape

    columns = {col["name"] for col in inspector.get_columns("transactions")}
    if "account_id" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN account_id VARCHAR"))

def init_db():
    print(f"🔌 Database URL: {engine.url}")
    Base.metadata.create_all(bind=engine)
    migrate_schema()
    seed_default_categories()

    # Verify tables were created
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"✅ Tables created: {tables}")

if __name__ == "__main__":
    init_db()
