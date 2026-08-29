import os

from app.config.database import Base, engine, SessionLocal
from app.models.user import User
from app.models.category import Category
from app.utils.crypto import decrypt, encrypt
from sqlalchemy import inspect, text

# Order matches the categories this app shipped with before custom
# categories existed — preserved via sort_order so existing pickers/filters
# don't reshuffle for users upgrading in place. "transfer"/"other" are
# "both" since they're equally valid for money going out or coming in;
# everything before them predates income categories and stays expense-only.
DEFAULT_CATEGORIES = [
    ("food", "🍔", "expense"),
    ("transport", "🚗", "expense"),
    ("shopping", "🛍️", "expense"),
    ("entertainment", "🎬", "expense"),
    ("health", "🏥", "expense"),
    ("utilities", "💡", "expense"),
    ("rent", "🏠", "expense"),
    ("subscriptions", "🔄", "expense"),
    ("transfer", "💸", "both"),
    ("other", "📌", "both"),
    ("salary", "💰", "income"),
    ("freelance", "💼", "income"),
    ("gift", "🎁", "income"),
    ("refund", "↩️", "income"),
    ("interest", "📈", "income"),
]

def seed_default_categories():
    db = SessionLocal()
    try:
        existing_names = {
            name for (name,) in db.query(Category.name).filter(Category.user_id.is_(None)).all()
        }
        for order, (name, icon, category_type) in enumerate(DEFAULT_CATEGORIES):
            if name in existing_names:
                continue
            db.add(Category(user_id=None, name=name, icon=icon, type=category_type, sort_order=order))
        db.commit()
    finally:
        db.close()

def encrypt_plaintext_gmail_tokens():
    """One-time-per-token cleanup: any gmail_refresh_token stored before
    encryption-at-rest was added is still plaintext. Idempotent and
    self-healing — a token that already decrypts successfully is left
    alone, so this is safe to run on every startup. No-ops entirely until
    ENCRYPTION_KEY is actually set, so deploying this code doesn't require
    the env var to exist yet."""
    if not os.getenv("ENCRYPTION_KEY"):
        return

    db = SessionLocal()
    try:
        users = db.query(User).filter(User.gmail_refresh_token.isnot(None)).all()
        for user in users:
            try:
                decrypt(user.gmail_refresh_token)
                continue  # already encrypted
            except Exception:
                pass
            user.gmail_refresh_token = encrypt(user.gmail_refresh_token)
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
            # Must match the model's Integer type — a Postgres DB that goes
            # through this path (rather than a fresh create_all) would
            # otherwise get a VARCHAR column, breaking account_id
            # comparisons/filters against the real Integer FK values.
            conn.execute(text("ALTER TABLE transactions ADD COLUMN account_id INTEGER"))

    if "users" in inspector.get_table_names():
        user_columns = {col["name"] for col in inspector.get_columns("users")}
        if "password_hash" not in user_columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN password_hash VARCHAR"))

    if "categories" in inspector.get_table_names():
        category_columns = {col["name"] for col in inspector.get_columns("categories")}
        if "type" not in category_columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE categories ADD COLUMN type VARCHAR NOT NULL DEFAULT 'expense'"))
                # Pre-existing defaults predate the expense/income split — transfer
                # and other apply to both, so they'd wrongly hide from the income
                # picker if left at the DEFAULT 'expense' the ALTER just applied.
                conn.execute(text(
                    "UPDATE categories SET type = 'both' "
                    "WHERE user_id IS NULL AND name IN ('transfer', 'other')"
                ))

    existing_index_names = {idx["name"] for idx in inspector.get_indexes("transactions")}
    if "uq_transactions_user_raw_text" not in existing_index_names:
        try:
            with engine.begin() as conn:
                conn.execute(text(
                    "CREATE UNIQUE INDEX uq_transactions_user_raw_text "
                    "ON transactions (user_id, raw_text) WHERE raw_text IS NOT NULL"
                ))
        except Exception as e:
            # Only fails if duplicate (user_id, raw_text) rows already exist
            # from before this constraint existed — don't block startup on
            # cleaning that up, just leave the app running unconstrained.
            print(f"⚠️  Could not create transaction dedup index (existing duplicates?): {e}")

def init_db():
    print(f"🔌 Database URL: {engine.url}")
    Base.metadata.create_all(bind=engine)
    migrate_schema()
    seed_default_categories()
    encrypt_plaintext_gmail_tokens()

    # Verify tables were created
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"✅ Tables created: {tables}")

if __name__ == "__main__":
    init_db()
