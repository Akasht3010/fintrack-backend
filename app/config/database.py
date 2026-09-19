import re
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool
import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set in .env file")

# Managed Postgres add-ons (Railway, Render, Heroku-style) commonly hand out
# a "postgres://" URL, but SQLAlchemy 1.4+ only recognizes "postgresql://" —
# rewrite it rather than erroring or silently falling through to the SQLite
# branch below.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# A Postgres URL embeds the password in plaintext (postgresql://user:pass@host/db)
# -- mask it before this ever reaches a log, even though nothing external
# currently captures stdout here.
_masked_database_url = re.sub(r"(://[^:/@]+:)[^@]+(@)", r"\1***\2", DATABASE_URL)
print(f"📦 Using database: {_masked_database_url}")

# Create engine
if DATABASE_URL.startswith("postgresql"):
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
else:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
