"""Chrome user-data-dir singleton lock cleanup (stale profile after crash)."""
from __future__ import annotations

import os
import re
from pathlib import Path

from app.logging_setup import get_logger

logger = get_logger(__name__)

_LOCK_NAMES = ("SingletonLock", "SingletonSocket", "SingletonCookie")
_HOST_PID_RE = re.compile(r"-(\d+)\s*$")


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _pid_from_lock_path(lock_path: Path) -> int | None:
    try:
        if lock_path.is_symlink():
            target = os.readlink(lock_path)
        elif lock_path.exists():
            target = lock_path.read_text(encoding="utf-8", errors="replace").strip()
        else:
            return None
    except OSError:
        return None
    match = _HOST_PID_RE.search(target.replace("\n", " "))
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    parts = target.replace("\\", "/").split("-")
    if len(parts) >= 2 and parts[-1].isdigit():
        return int(parts[-1])
    return None


def lock_holder_pid(profile_dir: Path) -> int | None:
    lock = profile_dir / "SingletonLock"
    if not lock.exists():
        return None
    return _pid_from_lock_path(lock)


def release_chrome_profile_lock(profile_dir: Path) -> list[str]:
    """Remove Chrome singleton files when the lock PID is dead or unreadable."""
    profile_dir = Path(profile_dir)
    if not profile_dir.is_dir():
        return []

    holder = lock_holder_pid(profile_dir)
    if holder is not None and process_alive(holder):
        logger.info(
            "chrome_profile_lock.kept",
            profile_dir=str(profile_dir),
            holder_pid=holder,
        )
        return []

    removed: list[str] = []
    for name in _LOCK_NAMES:
        path = profile_dir / name
        if not path.exists() and not path.is_symlink():
            continue
        try:
            path.unlink(missing_ok=True)
            removed.append(name)
        except OSError as exc:
            logger.warning(
                "chrome_profile_lock.unlink_failed",
                path=str(path),
                error=str(exc),
            )
    if removed:
        logger.info(
            "chrome_profile_lock.released",
            profile_dir=str(profile_dir),
            removed=removed,
            stale_pid=holder,
        )
    return removed
