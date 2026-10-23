"""Glue a soundtrack onto a finished silent clip without re-encoding video."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.config import Settings, get_settings
from app.video.compose import TIMEOUT_SECONDS, clip_duration

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aac", ".ogg"}
FADE_S = 1.0


class MuxError(RuntimeError):
    pass


def _safe_name(filename: str) -> str:
    name = Path(filename).name
    if not name or name != filename or ".." in name:
        raise MuxError("некорректное имя аудио")
    if Path(name).suffix.lower() not in AUDIO_EXTENSIONS:
        raise MuxError(f"неподдерживаемый звук: {name}")
    return name


def resolve_audio_file(filename: str, settings: Settings | None = None) -> Path:
    """Find an uploaded or generated audio file without leaving those folders."""
    settings = settings or get_settings()
    name = _safe_name(filename)
    for root in (settings.video_source_dir, settings.media_dir):
        folder = Path(root).resolve()
        candidate = (folder / name).resolve()
        if candidate.parent == folder and candidate.is_file():
            return candidate
    raise MuxError(f"аудио не найдено: {name}")


def mux_command(
    video: Path,
    output: Path,
    *,
    mode: str,
    audio: Path | None,
    duration_s: float,
) -> list[str]:
    """ffmpeg argv. Video stream is copied; only audio is encoded."""
    fade_at = max(0.0, duration_s - FADE_S)
    command = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video)]
    if mode == "generate":
        length = max(duration_s, 0.5)
        command += [
            "-f",
            "lavfi",
            "-t",
            f"{length:.3f}",
            "-i",
            "sine=frequency=196:sample_rate=44100,volume=0.08",
            "-f",
            "lavfi",
            "-t",
            f"{length:.3f}",
            "-i",
            "anoisesrc=color=pink:amplitude=0.02:sample_rate=44100",
            "-filter_complex",
            (
                "[1:a][2:a]amix=inputs=2:duration=shortest,"
                f"afade=t=out:st={fade_at:.3f}:d={FADE_S}[a]"
            ),
            "-map",
            "0:v:0",
            "-map",
            "[a]",
        ]
    elif mode == "library":
        if audio is None:
            raise MuxError("не задан файл звука")
        command += [
            "-stream_loop",
            "-1",
            "-i",
            str(audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-af",
            f"afade=t=out:st={fade_at:.3f}:d={FADE_S}",
        ]
    else:
        raise MuxError(f"неизвестный режим звука: {mode}")
    command += [
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output),
    ]
    return command


def mux_audio(
    video: Path,
    *,
    mode: str,
    filename: str | None = None,
    settings: Settings | None = None,
) -> None:
    """Replace ``video`` with the same picture plus an audio track.

    Failures leave the original file in place.
    """
    mode = (mode or "none").strip().lower()
    if mode in {"", "none"}:
        return
    if shutil.which("ffmpeg") is None:
        raise MuxError("ffmpeg не установлен")
    if not video.is_file():
        raise MuxError("ролик не найден")
    audio = resolve_audio_file(filename, settings) if mode == "library" else None
    duration = clip_duration(video) or 5.0
    handle, raw_name = tempfile.mkstemp(suffix=".mp4", dir=str(video.parent))
    os.close(handle)
    out = Path(raw_name)
    try:
        ran = subprocess.run(
            mux_command(video, out, mode=mode, audio=audio, duration_s=duration),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        out.unlink(missing_ok=True)
        raise MuxError("ffmpeg не успел приклеить звук") from exc
    if ran.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        out.unlink(missing_ok=True)
        detail = (ran.stderr or "").strip().splitlines()
        raise MuxError(detail[-1] if detail else "ffmpeg не приклеил звук")
    out.replace(video)
