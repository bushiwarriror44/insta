"""SQLite backup take, prune, list, restore."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.config import Settings
from app.services.backup import (
    BackupError,
    database_path,
    prune,
    resolve_backup,
    restore,
    take,
)


def test_database_path_rejects_non_sqlite():
    settings = Settings(_env_file=None, database_url="postgresql://x")
    with pytest.raises(BackupError, match="только для SQLite"):
        database_path(settings)


def test_take_creates_backup_file(app_env, monkeypatch):
    from app.config import settings as global_settings

    db_path = database_path(global_settings)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER)")
        conn.commit()

    backup = take(global_settings)
    assert backup.database.is_file()
    assert backup.database.name.startswith("app-")


def test_prune_keeps_newest(app_env, monkeypatch):
    from app.config import settings as global_settings

    dest = Path(global_settings.backup_dir)
    dest.mkdir(parents=True, exist_ok=True)
    for stamp in ("20260101-120000", "20260101-120001", "20260101-120002"):
        (dest / f"app-{stamp}.db").write_bytes(b"sqlite")
    monkeypatch.setattr(global_settings, "backup_keep", 2, raising=True)
    doomed = prune(global_settings)
    assert len(doomed) == 1
    assert len(list(dest.glob("app-*.db"))) == 2


def test_restore_keeps_previous_and_swaps_data(app_env, monkeypatch, tmp_path):
    from app.config import settings as global_settings

    live = tmp_path / "live.db"
    backups = tmp_path / "backups"
    monkeypatch.setattr(global_settings, "database_url", f"sqlite:///{live}", raising=True)
    monkeypatch.setattr(global_settings, "backup_dir", backups, raising=True)

    with sqlite3.connect(live) as conn:
        conn.execute("CREATE TABLE marker (v TEXT)")
        conn.execute("INSERT INTO marker VALUES ('live')")
        conn.commit()

    backup = take(global_settings)
    with sqlite3.connect(live) as conn:
        conn.execute("UPDATE marker SET v = 'changed'")
        conn.commit()

    restore(backup.database, global_settings)
    with sqlite3.connect(live) as conn:
        row = conn.execute("SELECT v FROM marker").fetchone()
    assert row[0] == "live"
    before = list(live.parent.glob("live.before-restore-*.db"))
    assert before


def test_resolve_backup_rejects_bad_names(app_env):
    from app.config import settings as global_settings

    with pytest.raises(BackupError, match="app-"):
        resolve_backup(global_settings, "evil.db")
    with pytest.raises(BackupError, match="app-"):
        resolve_backup(global_settings, "../../etc/passwd")


def test_restore_rejects_invalid_name(app_env):
    from app.config import settings as global_settings

    with pytest.raises(BackupError):
        restore(Path("not-app.db"), global_settings)
