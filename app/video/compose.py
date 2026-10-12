"""Joining clips into one post, over a soundtrack.

A five-second silent clip is not a Reel. This turns several of them into
one vertical video with sound, which is the shape all three platforms
actually want.

Two decisions worth stating:

* **Every clip is re-encoded through a filter graph**, not concatenated
  with the demuxer. The demuxer needs identical codecs, resolutions and
  frame rates; clips here come from different models and from an
  operator's own uploads, and a mismatch there produces a file that plays
  for one second and then freezes rather than an error.
* **A short track is looped rather than truncating the video.** The
  footage is the post; the music is under it. `-shortest` alone would cut
  a 30-second edit down to a 10-second song.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Vertical. Every one of the three platforms wants 9:16.
DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1920
DEFAULT_FPS = 30

#: Encoding a minute of 1080x1920 takes a while on a small machine, and a
#: hung ffmpeg must not hold the worker forever.
TIMEOUT_SECONDS = 900


class ComposeError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(slots=True)
class ComposeRequest:
    clips: list[Path]
    output: Path
    audio: Path | None = None
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    fps: int = DEFAULT_FPS
    audio_fade_out_s: float = 1.5


def _clip_filters(count: int, width: int, height: int, fps: int) -> str:
    """Scale, crop and normalise each clip, then join them.

    Cropping to fill rather than padding to fit: a letterboxed Reel with
    black bars down the sides reads as a mistake on a phone.
    """
    parts = []
    for index in range(count):
        parts.append(
            f"[{index}:v]"
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            f"setsar=1,fps={fps},format=yuv420p"
            f"[v{index}]"
        )
    joined = "".join(f"[v{index}]" for index in range(count))
    parts.append(f"{joined}concat=n={count}:v=1:a=0[v]")
    return ";".join(parts)


def clip_duration(path: Path) -> float:
    """Seconds of video, read from the file itself."""
    try:
        raw = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout
        return float(json.loads(raw)["format"]["duration"])
    except (subprocess.SubprocessError, KeyError, ValueError, json.JSONDecodeError):
        return 0.0


def total_duration(clips: list[Path]) -> float:
    return sum(clip_duration(clip) for clip in clips)


def fade_start(total: float, fade: float) -> float:
    """When the fade begins.

    `afade` measures from the start of the stream, so a fade-out needs to
    be told where the end is. Getting this wrong does not fail: it fades
    the track out at the beginning and leaves the rest of the post silent,
    while the file still reports a perfectly good audio stream.
    """
    if total <= 0:
        return 0.0
    return max(0.0, total - fade)


def build_command(request: ComposeRequest, total: float | None = None) -> list[str]:
    """The ffmpeg invocation, as a list so nothing is shell-interpreted."""
    if not request.clips:
        raise ComposeError("для склейки нужен хотя бы один клип")

    command = ["ffmpeg", "-y", "-loglevel", "error"]
    for clip in request.clips:
        command += ["-i", str(clip)]

    if request.audio is not None:
        # Loop the track so the footage decides the length, not the song.
        command += ["-stream_loop", "-1", "-i", str(request.audio)]

    filters = _clip_filters(
        len(request.clips), request.width, request.height, request.fps
    )
    audio_index = len(request.clips)

    command += ["-filter_complex", filters, "-map", "[v]"]

    if request.audio is not None:
        command += ["-map", f"{audio_index}:a"]
        if request.audio_fade_out_s > 0:
            length = total if total is not None else total_duration(request.clips)
            start = fade_start(length, request.audio_fade_out_s)
            command += [
                "-af",
                f"afade=t=out:st={start:.3f}:d={request.audio_fade_out_s}",
            ]
        command += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    else:
        command += ["-an"]

    command += [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        # A phone player wants the index at the front.
        "-movflags",
        "+faststart",
        str(request.output),
    ]
    return command


def compose(request: ComposeRequest) -> Path:
    """Render the composition. Raises `ComposeError` on failure."""
    if shutil.which("ffmpeg") is None:
        raise ComposeError("ffmpeg не установлен")
    for clip in request.clips:
        if not clip.is_file():
            raise ComposeError(f"клип не найден: {clip.name}")
    if request.audio is not None and not request.audio.is_file():
        raise ComposeError(f"аудио не найдено: {request.audio.name}")

    request.output.parent.mkdir(parents=True, exist_ok=True)

    try:
        finished = subprocess.run(
            build_command(request),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        request.output.unlink(missing_ok=True)
        raise ComposeError(
            f"ffmpeg не завершился за {TIMEOUT_SECONDS}с", retryable=True
        ) from exc

    if finished.returncode != 0:
        request.output.unlink(missing_ok=True)
        # ffmpeg's last line is the one that says what went wrong.
        detail = (finished.stderr or "").strip().splitlines()
        raise ComposeError(detail[-1] if detail else "ошибка ffmpeg")

    if not request.output.is_file() or request.output.stat().st_size == 0:
        request.output.unlink(missing_ok=True)
        raise ComposeError("ffmpeg не создал файл")

    return request.output
