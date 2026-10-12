"""SQLite copies the operator can take from the panel."""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings, get_settings

STAMP = "%Y%m%d-%H%M%S"


class BackupError(RuntimeError):
    pass


@dataclass(slots=True)
class Backup:
    database: Path
    taken_at: datetime

    @property
    def bytes(self) -> int:
        return self.database.stat().st_size


def database_path(settings: Settings) -> Path:
    url = settings.database_url
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise BackupError(
            f"резервные копии поддерживаются только для SQLite, не для {url.split(':', 1)[0]}"
        )
    return Path(url[len(prefix) :])


def take(settings: Settings | None = None, *, now: datetime | None = None) -> Backup:
    settings = settings or get_settings()
    now = now or datetime.now(timezone.utc)
    source = database_path(settings)
    if not source.exists():
        raise BackupError(f"база данных не найдена: {source}")

    destination = Path(settings.backup_dir)
    destination.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime(STAMP)
    db_copy = destination / f"app-{stamp}.db"

    try:
        with sqlite3.connect(source) as live, sqlite3.connect(db_copy) as copy:
            live.backup(copy)
    except sqlite3.Error as exc:
        db_copy.unlink(missing_ok=True)
        raise BackupError(f"не удалось скопировать базу данных: {exc}") from exc

    prune(settings)
    return Backup(database=db_copy, taken_at=now)


def prune(settings: Settings | None = None) -> list[Path]:
    settings = settings or get_settings()
    destination = Path(settings.backup_dir)
    if not destination.exists():
        return []
    nights = sorted(
        (path.stem[len("app-") :] for path in destination.glob("app-*.db")),
        reverse=True,
    )
    doomed: list[Path] = []
    for stamp in nights[settings.backup_keep :]:
        path = destination / f"app-{stamp}.db"
        if path.exists():
            path.unlink()
            doomed.append(path)
    return doomed


def resolve_backup(settings: Settings, name: str) -> Path:
    """Map a backup filename to a path inside ``backup_dir``, rejecting traversal."""
    destination = Path(settings.backup_dir).resolve()
    filename = Path(name).name
    if not filename.endswith(".db") or not Path(filename).stem.startswith("app-"):
        raise BackupError(
            "имя бэкапа должно быть файлом app-*.db в каталоге резервных копий"
        )
    candidate = (destination / filename).resolve()
    if candidate.parent != destination:
        raise BackupError("имя бэкапа выходит за пределы каталога резервных копий")
    return candidate


def list_backups(settings: Settings | None = None) -> list[Backup]:
    settings = settings or get_settings()
    destination = Path(settings.backup_dir)
    if not destination.exists():
        return []
    rows: list[Backup] = []
    for path in sorted(destination.glob("app-*.db"), reverse=True):
        stamp = path.stem[len("app-") :]
        try:
            taken = datetime.strptime(stamp, STAMP).replace(tzinfo=timezone.utc)
        except ValueError:
            taken = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        rows.append(Backup(database=path, taken_at=taken))
    return rows


def restore(archive: Path, settings: Settings | None = None) -> Path:
    """Overwrite the live SQLite file. Restart API and worker after restore."""
    settings = settings or get_settings()
    archive = resolve_backup(settings, archive.name)
    if not archive.exists():
        raise BackupError(f"бэкап не найден: {archive.name}")
    target = database_path(settings)
    if target.exists():
        kept = target.with_suffix(
            f".before-restore-{datetime.now(timezone.utc):{STAMP}}.db"
        )
        shutil.copy2(target, kept)
    shutil.copy2(archive, target)
    return target
