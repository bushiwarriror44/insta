"""SQLAlchemy engine, session factory, schema bootstrap."""
from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
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
    ("accounts", "backup_codes", "TEXT"),
    ("accounts", "login_surface", "VARCHAR(16)"),
    ("proxies", "last_geo_country", "VARCHAR(8)"),
    ("post_jobs", "post_type", "VARCHAR(32)"),
    ("post_logs", "post_type", "VARCHAR(32)"),
    ("post_logs", "last_stats_at", "DATETIME"),
    ("post_logs", "view_count", "INTEGER"),
    ("post_logs", "like_count", "INTEGER"),
    ("post_logs", "comment_count", "INTEGER"),
    ("post_logs", "play_count", "INTEGER"),
    ("post_logs", "save_count", "INTEGER"),
    ("post_logs", "share_count", "INTEGER"),
    ("post_logs", "raw_stats_json", "TEXT"),
]


def _apply_pending_columns() -> None:
    """ALTER TABLE ADD COLUMN for any column that exists in models but not yet on disk."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table, column, sqltype in _PENDING_COLUMNS:
        if table not in existing_tables:
            continue
        cols = {c["name"] for c in inspector.get_columns(table)}
        if column in cols:
            continue
        with engine.begin() as conn:
            conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {sqltype}'))


def init_db() -> None:
    """Create missing tables and apply backwards-compatible column additions."""
    from app.db.models import Base  # noqa: WPS433

    Base.metadata.create_all(bind=engine)
    _apply_pending_columns()
