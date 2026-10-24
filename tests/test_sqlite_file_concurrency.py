"""File-backed SQLite must not share one connection across threads.

Runs in a subprocess because app.config.database builds its engine at
import time from DATABASE_URL, and the rest of the suite needs :memory:.
"""
import subprocess
import sys
import textwrap


def test_file_sqlite_engine_survives_concurrent_sessions(tmp_path):
    db_file = tmp_path / "dev.db"
    script = textwrap.dedent(f"""
        import os
        os.environ["DATABASE_URL"] = "sqlite:///{db_file}"
        from concurrent.futures import ThreadPoolExecutor
        from sqlalchemy import text
        from sqlalchemy.pool import StaticPool
        from app.config.database import engine, SessionLocal

        assert not isinstance(engine.pool, StaticPool), type(engine.pool)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, a TEXT, b TEXT, c TEXT)"))
            for i in range(200):
                conn.execute(text("INSERT INTO t (a, b, c) VALUES ('x', 'y', 'z')"))

        def work(_):
            with SessionLocal() as db:
                for _ in range(20):
                    rows = db.execute(text("SELECT id, a, b, c FROM t")).all()
                    assert len(rows) == 200 and all(len(r) == 4 for r in rows)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(work, range(32)))
        print("OK")
    """)
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "OK" in result.stdout
