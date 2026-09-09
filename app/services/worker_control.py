"""Start and stop the agent/worker from the panel.

The command is fixed: this interpreter, ``-m app.cli run-worker``. Nothing
from the HTTP request is interpolated into a shell.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from app.config import settings


class WorkerProblem(Exception):
    """The worker could not be started or stopped."""


@dataclass
class Running:
    alive: bool
    pid: int | None = None


def _pid_file() -> Path:
    return Path(settings.data_dir) / "worker.pid"


def status() -> Running:
    pid = _stored_pid()
    if pid is None:
        return Running(alive=False)
    live = _alive(pid)
    return Running(alive=live, pid=pid if live else None)


def ensure_started(*, heartbeat_alive: bool = False) -> Running | None:
    """Start the worker unless this process or another worker is already live.

    Returns the panel-spawned process, or ``None`` when an outside worker
    (Docker/CLI) is already beating. Stop from the panel does not call this.
    """
    already = status()
    if already.alive:
        return already
    if heartbeat_alive:
        return None
    return start()


def start() -> Running:
    already = status()
    if already.alive:
        return already

    popen_kwargs: dict = {
        "cwd": str(Path.cwd()),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "app.cli", "run-worker"],
            **popen_kwargs,
        )
    except OSError as exc:
        raise WorkerProblem(f"не удалось запустить агента: {exc}") from exc

    path = _pid_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(process.pid), encoding="utf-8")
    return Running(alive=True, pid=process.pid)


def stop() -> Running:
    running = status()
    if not running.alive or running.pid is None:
        _forget()
        return Running(alive=False)

    try:
        _ask_to_stop(running.pid)
    except (OSError, ProcessLookupError):
        _forget()
        return Running(alive=False)

    _forget()
    return Running(alive=False, pid=running.pid)


def _ask_to_stop(pid: int) -> None:
    if sys.platform == "win32":
        try:
            os.kill(pid, signal.CTRL_BREAK_EVENT)
            return
        except OSError:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T"],
                capture_output=True,
                check=False,
            )
            return
    os.killpg(os.getpgid(pid), signal.SIGTERM)


def _stored_pid() -> int | None:
    try:
        return int(_pid_file().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        if sys.platform == "win32":
            return _pid_exists_windows(pid)
        return False


def _pid_exists_windows(pid: int) -> bool:
    import ctypes

    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


def _forget() -> None:
    _pid_file().unlink(missing_ok=True)
