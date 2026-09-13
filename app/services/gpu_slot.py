"""One GPU card: chat or video, not both.

The admin panel and the worker share ``data/gpu_slot.lock`` so a render
can unload Ollama and a chat that arrives mid-clip waits instead of
pulling the model back into VRAM.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.config import Settings, get_settings
from app.generation.base import GenerationError

LOCK_NAME = "gpu_slot.lock"
REASON_VIDEO = "video"


def lock_path(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    return Path(settings.data_dir) / LOCK_NAME


def video_busy(settings: Settings | None = None) -> str | None:
    """Why the GPU is reserved, or None if chat may load."""
    settings = settings or get_settings()
    path = lock_path(settings)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return REASON_VIDEO
    ts = float(data.get("ts") or 0)
    stale_s = float(data.get("stale_s") or 0) or 1020.0
    if ts and (time.time() - ts) > stale_s:
        try:
            path.unlink()
        except OSError:
            pass
        return None
    return str(data.get("reason") or REASON_VIDEO)


@contextmanager
def hold_for_video(settings: Settings | None = None) -> Iterator[None]:
    settings = settings or get_settings()
    path = lock_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    stale_s = max(120.0, float(settings.generation_timeout_seconds) + 120.0)
    payload = json.dumps(
        {"reason": REASON_VIDEO, "ts": time.time(), "stale_s": stale_s},
        ensure_ascii=False,
    )
    for _ in range(8):
        if video_busy(settings) is not None:
            raise GenerationError(
                "GPU уже занята рендером — подождите окончания ролика",
                retryable=True,
            )
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            time.sleep(0.15)
            continue
        try:
            os.write(fd, payload.encode("utf-8"))
        finally:
            os.close(fd)
        break
    else:
        raise GenerationError(
            "GPU уже занята рендером — подождите окончания ролика",
            retryable=True,
        )
    try:
        yield
    finally:
        try:
            path.unlink()
        except OSError:
            pass
