"""Start Ollama and pull the agent model so the panel can talk without a click."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.services.runtime import probe


class OllamaProblem(Exception):
    """Ollama could not be started or the model could not be pulled."""


@dataclass
class OllamaStatus:
    reachable: bool
    pid: int | None = None
    model_ready: bool = False
    detail: str = ""


def _pid_file() -> Path:
    return Path(settings.data_dir) / "ollama.pid"


def _binary() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    if local.is_file():
        return str(local)
    unix = Path("/usr/local/bin/ollama")
    if unix.is_file():
        return str(unix)
    return None


def ensure_started(*, pull: bool = True) -> OllamaStatus:
    """Bring up ``ollama serve`` if this host should run it, then the model.

    Docker Compose talks to a sibling ``reels-ollama`` container instead; that
    path is already reachable and we do not spawn a second server.
    """
    if not settings.ollama_autostart:
        return OllamaStatus(reachable=False, detail="автозапуск отключён")

    current = probe()
    if current.reachable:
        ready = _model_ready(current.models)
        if pull and not ready:
            _pull()
            current = probe()
            ready = _model_ready(current.models)
        return OllamaStatus(reachable=True, model_ready=ready, detail=current.detail or "")

    binary = _binary()
    if binary is None:
        raise OllamaProblem(
            "Ollama не установлена. Поставьте её (winget install Ollama.Ollama) "
            "или поднимите сервис reels-ollama в docker compose."
        )

    pid = _spawn(binary)
    if not _wait_until_up(timeout=20.0):
        raise OllamaProblem("Ollama не ответила после запуска")

    ready = False
    if pull:
        _pull()
        current = probe()
        ready = _model_ready(current.models)
    return OllamaStatus(reachable=True, pid=pid, model_ready=ready)


def model_is_ready(models: list[str] | None = None) -> bool:
    if models is None:
        models = probe().models
    return _model_ready(models)


def _model_ready(models: list[str]) -> bool:
    wanted = settings.agent_model.strip()
    if not wanted:
        return False
    names = {m.split(":")[0] for m in models}
    return wanted in models or wanted.split(":")[0] in names or any(
        m.startswith(wanted) or wanted.startswith(m.split(":")[0]) for m in models
    )


def _spawn(binary: str) -> int:
    popen_kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen([binary, "serve"], **popen_kwargs)
    except OSError as exc:
        raise OllamaProblem(f"не удалось запустить Ollama: {exc}") from exc
    path = _pid_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(process.pid), encoding="utf-8")
    return process.pid


def _wait_until_up(*, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if probe().reachable:
            return True
        time.sleep(0.4)
    return False


_pull_lock = threading.Lock()
_pulling = False


def pull_in_background() -> None:
    global _pulling
    with _pull_lock:
        if _pulling:
            return
        _pulling = True

    def run() -> None:
        global _pulling
        try:
            _pull()
        finally:
            with _pull_lock:
                _pulling = False

    threading.Thread(target=run, name="ollama-pull", daemon=True).start()


def _pull() -> None:
    binary = _binary()
    if binary is None:
        return
    model = settings.agent_model.strip()
    if not model:
        return
    kwargs: dict = {
        "check": False,
        "timeout": 3600,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        subprocess.run([binary, "pull", model], **kwargs)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OllamaProblem(f"не удалось скачать модель {model}: {exc}") from exc
