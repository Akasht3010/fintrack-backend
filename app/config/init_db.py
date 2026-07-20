from app.config.database import Base, engine
from app.models.user import User
from app.models.transaction import Transaction
from app.models.budget import Budget
from sqlalchemy import inspect

def init_db():
    print(f"🔌 Database URL: {engine.url}")
    Base.metadata.create_all(bind=engine)
    
    # Verify tables were created
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"✅ Tables created: {tables}")

if __name__ == "__main__":
    init_db()
