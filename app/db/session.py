"""SQLAlchemy engine, session factory, schema bootstrap."""
from __future__ import annotations

from sqlalchemy import create_engine, event, inspect, text
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
    ("generation_jobs", "input_mode", "VARCHAR(32) DEFAULT 'text_only'"),
    ("generation_jobs", "reference_json", "TEXT"),
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
