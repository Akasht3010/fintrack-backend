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
elif ":memory:" in DATABASE_URL:
    # In-memory SQLite (the test suite): StaticPool makes every session share
    # one connection, since each new :memory: connection is a separate,
    # empty database.
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
else:
    # File-based SQLite (local dev): a normal pool, one connection per
    # thread. Route handlers are sync and run concurrently in the
    # threadpool, so sharing a single connection (StaticPool) let parallel
    # requests interleave on one cursor — rows came back corrupted
    # (IndexError inside SQLAlchemy) and requests failed with 500s/401s.
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
