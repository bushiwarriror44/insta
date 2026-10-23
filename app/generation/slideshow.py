"""Ken Burns / slideshow clips via ffmpeg (no GPU model)."""
from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

from app.config import Settings, get_settings
from app.generation.base import (
    INPUT_MODE_SLIDESHOW,
    REF_START_IMAGE,
    STAGE_RENDERING,
    GenerationError,
    GenerationRequest,
    GenerationResult,
    Progress,
    ProgressCallback,
    VideoBackend,
)
from app.video.compose import TIMEOUT_SECONDS


def slideshow_ffmpeg_command(
    images: list[Path],
    dest: Path,
    duration: float,
    width: int,
    height: int,
) -> list[str]:
    """Ken Burns over one still, or equal slices concatenated for several stills."""
    if not images:
        raise GenerationError("slideshow: нет изображений")
    if len(images) == 1:
        frames = max(1, int(duration * 30))
        vf = (
            f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            f"zoompan=z='min(zoom+0.0015,1.3)':d={frames}:s={width}x{height}:fps=30"
        )
        return [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            str(images[0]),
            "-vf",
            vf,
            "-t",
            str(duration),
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            str(dest),
        ]

    per = max(duration / len(images), 1 / 30)
    frames = max(1, int(round(per * 30)))
    command = ["ffmpeg", "-y"]
    filters: list[str] = []
    for index, image in enumerate(images):
        command += ["-loop", "1", "-i", str(image)]
        filters.append(
            f"[{index}:v]scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            f"zoompan=z='min(zoom+0.0015,1.3)':d={frames}:s={width}x{height}:fps=30[v{index}]"
        )
    joined = "".join(f"[v{index}]" for index in range(len(images)))
    filters.append(f"{joined}concat=n={len(images)}:v=1:a=0[v]")
    command += [
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[v]",
        "-pix_fmt",
        "yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        str(dest),
    ]
    return command


class SlideshowVideoBackend(VideoBackend):
    name = "slideshow"
    model_licence = "ffmpeg (no ML)"
    supports_text = False
    supports_slideshow = True

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def healthcheck(self) -> bool:
        try:
            subprocess.run(
                ["ffmpeg", "-version"],
                check=True,
                capture_output=True,
                timeout=10,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def health_detail(self) -> str:
        if self.healthcheck():
            return ""
        return "ffmpeg не найден — slideshow недоступен"

    def generate(
        self,
        request: GenerationRequest,
        out_dir: Path,
        on_progress: ProgressCallback | None = None,
    ) -> GenerationResult:
        if request.mode != INPUT_MODE_SLIDESHOW:
            raise GenerationError("slideshow backend только для image_slideshow")
        images = [ref.path for ref in request.references if ref.role in {
            REF_START_IMAGE,
            "end_image",
            "style_image",
        }]
        if not images:
            images = [ref.path for ref in request.references]
        if not images:
            raise GenerationError("slideshow: нет изображений")
        report = on_progress or (lambda _: None)
        report(Progress(STAGE_RENDERING))
        duration = max(1.0, float(request.duration_s))
        width = int(request.width)
        height = int(request.height)
        dest = out_dir / f"slideshow-{uuid.uuid4().hex}.mp4"
        cmd = slideshow_ffmpeg_command(images, dest, duration, width, height)
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=TIMEOUT_SECONDS)
        except FileNotFoundError as exc:
            raise GenerationError(self.health_detail()) from exc
        except subprocess.TimeoutExpired as exc:
            raise GenerationError("slideshow: таймаут ffmpeg", retryable=True) from exc
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr or b"").decode(errors="replace")[-400:]
            raise GenerationError(f"slideshow ffmpeg: {err or exc}") from exc
        if not dest.is_file():
            raise GenerationError("slideshow: выходной файл не создан")
        return GenerationResult(
            video_path=dest,
            generator="slideshow",
            cost_usd=0.0,
            backend=self.name,
        )
