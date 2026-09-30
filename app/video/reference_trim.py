"""Trim long reference clips before V2V upload."""
from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

from app.config import Settings, get_settings
from app.generation.base import GenerationError
from app.video.compose import clip_duration


def ensure_video_reference(
    path: Path,
    settings: Settings | None = None,
    *,
    max_duration_s: float = 15.0,
) -> Path:
    settings = settings or get_settings()
    try:
        duration = clip_duration(path)
    except Exception:
        duration = max_duration_s + 1.0
    if duration <= max_duration_s:
        return path
    out_dir = settings.media_dir / "_refs"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"trim-{uuid.uuid4().hex}.mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(path),
        "-t",
        str(max_duration_s),
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-an",
        str(dest),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise GenerationError(f"не удалось обрезать видео-референс: {exc}") from exc
    if not dest.is_file():
        raise GenerationError("ffmpeg не создал обрезанный референс")
    return dest
