"""SQLAlchemy engine, session factory, schema bootstrap."""
from __future__ import annotations

import contextlib
import os
import time

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def on_sqlite_connect(dbapi_connection, _connection_record) -> None:
    """Shared pragmas for api + worker on one SQLite file (Docker ./data)."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def attach_sqlite_pragmas(eng) -> None:
    if not str(eng.url).startswith("sqlite"):
        return
    if getattr(eng, "_sqlite_pragmas_attached", False):
        return
    event.listens_for(eng, "connect")(on_sqlite_connect)
    eng._sqlite_pragmas_attached = True  # type: ignore[attr-defined]


attach_sqlite_pragmas(engine)


# ---------------------------------------------------------------------------
# Idempotent in-place migrations.
#
# Project still uses ``Base.metadata.create_all`` for simplicity; that creates
# missing tables but won't add new columns to existing ones. The list below
# contains backwards-compatible additions (always nullable, no defaults) so a
# deployment that has been running before this release picks them up
# automatically. New tables continue to be handled by ``create_all``.
# ---------------------------------------------------------------------------

_PENDING_COLUMNS: list[tuple[str, str, str]] = [
    ("accounts", "last_idle_warmup_at", "DATETIME"),
    ("accounts", "last_session_rotation_at", "DATETIME"),
    ("accounts", "cooldown_until", "DATETIME"),
    ("accounts", "caption_profile", "VARCHAR(32)"),
    ("accounts", "session_id", "VARCHAR(1000)"),
    ("accounts", "login_identifier", "VARCHAR(200)"),
    ("accounts", "email", "VARCHAR(200)"),
    ("accounts", "email_password", "VARCHAR(500)"),
    ("accounts", "imap_host", "VARCHAR(200)"),
    ("accounts", "totp_seed", "VARCHAR(120)"),
    ("accounts", "backup_codes", "TEXT"),
    ("accounts", "login_surface", "VARCHAR(16)"),
    ("accounts", "platform", "VARCHAR(16) DEFAULT 'instagram'"),
    ("accounts", "brief", "TEXT DEFAULT ''"),
    ("accounts", "hold_for_review", "BOOLEAN DEFAULT 0"),
    ("accounts", "daily_spend_cap_usd", "FLOAT DEFAULT 0"),
    ("proxies", "last_geo_country", "VARCHAR(8)"),
    ("post_jobs", "post_type", "VARCHAR(32)"),
    ("post_jobs", "title", "VARCHAR(255)"),
    ("post_jobs", "description", "TEXT"),
    ("post_jobs", "tags", "TEXT"),
    ("post_jobs", "privacy", "VARCHAR(32)"),
    ("post_jobs", "permalink", "TEXT"),
    ("post_logs", "post_type", "VARCHAR(32)"),
    ("post_logs", "last_stats_at", "DATETIME"),
    ("post_logs", "view_count", "INTEGER"),
    ("post_logs", "like_count", "INTEGER"),
    ("post_logs", "comment_count", "INTEGER"),
    ("post_logs", "play_count", "INTEGER"),
    ("post_logs", "save_count", "INTEGER"),
    ("post_logs", "share_count", "INTEGER"),
    ("post_logs", "raw_stats_json", "TEXT"),
    ("panel_settings", "admin_notes", "TEXT DEFAULT ''"),
    ("panel_settings", "llm_gateway_token", "VARCHAR(120)"),
    ("panel_settings", "llm_gateway_enabled", "BOOLEAN DEFAULT 1"),
    ("panel_settings", "floppydata_api_key", "VARCHAR(500)"),
    ("panel_settings", "floppydata_last_form", "TEXT"),
    ("generation_jobs", "input_mode", "VARCHAR(32) DEFAULT 'text_only'"),
    ("generation_jobs", "reference_json", "TEXT"),
    ("generation_jobs", "audio_mode", "VARCHAR(16) DEFAULT 'none'"),
    ("generation_jobs", "audio_filename", "VARCHAR(255)"),
]


def _duplicate_column_error(exc: BaseException) -> bool:
    return "duplicate column name" in str(exc).lower()


@contextlib.contextmanager
def _init_db_migration_lock():
    """One ALTER writer at a time when api and worker share ./data (Docker)."""
    if not str(engine.url).startswith("sqlite"):
        yield
        return
    lock_path = settings.data_dir / ".init_db.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    acquired = False
    for _ in range(120):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            acquired = True
            break
        except FileExistsError:
            time.sleep(0.1)
    if not acquired:
        raise TimeoutError("таймаут ожидания блокировки миграции init_db")
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def _apply_pending_columns() -> None:
    """ALTER TABLE ADD COLUMN for any column that exists in models but not yet on disk."""
    with _init_db_migration_lock():
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())
        for table, column, sqltype in _PENDING_COLUMNS:
            if table not in existing_tables:
                continue
            cols = {c["name"] for c in inspector.get_columns(table)}
            if column in cols:
                continue
            try:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sqltype}"))
            except OperationalError as exc:
                if _duplicate_column_error(exc):
                    continue
                raise


def _ensure_account_platform_username_index() -> None:
    """Backfill UNIQUE(platform, username) on DBs created before multi-platform accounts."""
    inspector = inspect(engine)
    if "accounts" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_account_platform_username "
                "ON accounts (platform, username)"
            )
        )


def init_db() -> None:
    """Create missing tables and apply backwards-compatible column additions."""
    from app.db.models import Base  # noqa: WPS433

    Base.metadata.create_all(bind=engine)
    _apply_pending_columns()
    _ensure_account_platform_username_index()
    from app.agent.presets import seed_if_empty

    with SessionLocal() as session:
        seed_if_empty(session)
