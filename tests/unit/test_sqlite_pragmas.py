"""SQLite pragmas and platform/username index bootstrap."""
from __future__ import annotations

from sqlalchemy import inspect, text

from app.db.session import init_db, on_sqlite_connect


def test_sqlite_connection_uses_wal(app_env):
    with app_env.engine.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar()
    assert str(mode).lower() == "wal"


def test_init_db_creates_platform_username_unique_index(app_env):
    init_db()
    indexes = {idx["name"] for idx in inspect(app_env.engine).get_indexes("accounts")}
    assert "uq_account_platform_username" in indexes


def test_on_sqlite_connect_sets_foreign_keys(app_env):
    raw = app_env.engine.raw_connection()
    try:
        on_sqlite_connect(raw, None)
        cur = raw.cursor()
        cur.execute("PRAGMA foreign_keys")
        assert cur.fetchone()[0] == 1
    finally:
        raw.close()
