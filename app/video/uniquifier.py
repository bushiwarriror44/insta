"""ffmpeg-based video uniquifier for Reels.

Why this is non-trivial: Instagram fingerprints uploads with multiple
techniques — cryptographic hashes, perceptual hashes, audio fingerprints,
encoder telemetry. A single deterministic trim does not move the needle.

This module re-encodes every video with a randomized subset of:
- Geometry: crop 1-4 % per side, optional zoom 1.01-1.04, optional mirror.
- Color: brightness/contrast/saturation/gamma in ±3 % range.
- Audio: pitch ±1-3 cents, volume ±0.5 dB, optional atempo 0.99-1.01.
- Codec: libx264, CRF 20-24, random preset, random keyframe interval.
- Container: -map_metadata -1, randomized creation_time, +faststart.
- Timing: random trim of 30-300 ms from start and end.

Output is reusable across accounts but never bit-identical.
"""
from __future__ import annotations

import json
import random
import secrets
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import imageio_ffmpeg

from app.logging_setup import get_logger

logger = get_logger(__name__)


def ffmpeg_bin() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def ffprobe_bin() -> str:
    bundled = shutil.which("ffprobe")
    if bundled:
        return bundled
    raise RuntimeError(
        "ffprobe not found on PATH. Install ffmpeg system package or add ffprobe alongside ffmpeg."
    )


@dataclass
class UniquifyParams:
    crop_left_pct: float = 0.0
    crop_right_pct: float = 0.0
    crop_top_pct: float = 0.0
    crop_bottom_pct: float = 0.0
    zoom: float = 1.0
    mirror: bool = False
    brightness: float = 0.0
    contrast: float = 1.0
    saturation: float = 1.0
    gamma: float = 1.0
    audio_pitch_cents: float = 0.0
    audio_volume_db: float = 0.0
    audio_atempo: float = 1.0
    audio_eq_freq: int | None = None  # equalizer center frequency, Hz
    audio_eq_gain: float = 0.0  # equalizer gain, dB
    crf: int = 22
    preset: str = "medium"
    audio_bitrate_kbps: int = 128
    keyint: int = 60
    trim_start_ms: int = 0
    trim_end_ms: int = 0
    creation_time_iso: str = ""
    # Sub-pixel resolution jitter to perturb encoder output without breaking
    # 1080×1920 framing. Applies a roundtrip ``scale`` to width*resize_pct
    # then back to the original. Values close to 1.0 (0.99–1.005) are safe.
    resolution_jitter_pct: float = 1.0
    # If True, an extra crop covers the right-top corner where TikTok / CapCut
    # watermarks usually live. Off by default.
    assume_tiktok_watermark: bool = False
    extra: dict[str, str] = field(default_factory=dict)


def random_params(
    rng: Optional[random.Random] = None,
    allow_mirror: bool = False,
    *,
    assume_tiktok_watermark: bool = False,
) -> UniquifyParams:
    rng = rng or random.Random()
    presets = ["medium", "fast", "slow", "veryfast"]
    creation = datetime.now(timezone.utc) - timedelta(
        days=rng.randint(0, 30), hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
    )
    eq_freq = None
    eq_gain = 0.0
    if rng.random() < 0.6:  # 60% of clips get a subtle audio EQ tweak
        eq_freq = rng.choice([120, 200, 400, 800, 1600, 3200])
        eq_gain = rng.uniform(-1.5, 1.5)
    return UniquifyParams(
        crop_left_pct=rng.uniform(0.5, 3.0),
        crop_right_pct=rng.uniform(0.5, 3.0),
        crop_top_pct=rng.uniform(0.5, 3.0),
        crop_bottom_pct=rng.uniform(0.5, 3.0),
        zoom=rng.uniform(1.005, 1.03),
        mirror=allow_mirror and (rng.random() < 0.05),
        brightness=rng.uniform(-0.03, 0.03),
        contrast=rng.uniform(0.97, 1.03),
        saturation=rng.uniform(0.97, 1.03),
        gamma=rng.uniform(0.97, 1.03),
        audio_pitch_cents=rng.uniform(-3.0, 3.0),
        audio_volume_db=rng.uniform(-0.5, 0.5),
        audio_atempo=rng.uniform(0.99, 1.01),
        audio_eq_freq=eq_freq,
        audio_eq_gain=eq_gain,
        crf=rng.randint(20, 24),
        preset=rng.choice(presets),
        audio_bitrate_kbps=rng.choice([96, 112, 128, 144, 160, 192]),
        keyint=rng.randint(48, 90),
        trim_start_ms=rng.randint(0, 250),
        trim_end_ms=rng.randint(30, 300),
        creation_time_iso=creation.strftime("%Y-%m-%dT%H:%M:%S"),
        resolution_jitter_pct=rng.uniform(0.99, 1.005),
        assume_tiktok_watermark=assume_tiktok_watermark,
    )


@dataclass
class VideoMeta:
    width: int
    height: int
    duration_sec: float
    fps: float
    has_audio: bool


def probe(path: Path) -> VideoMeta:
    out = subprocess.check_output(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ],
        stderr=subprocess.PIPE,
    )
    data = json.loads(out)
    width = height = 0
    fps = 30.0
    has_audio = False
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
            r_frame_rate = stream.get("r_frame_rate", "30/1")
            try:
                num, den = r_frame_rate.split("/")
                fps = float(num) / float(den) if float(den) else float(num)
            except (ValueError, ZeroDivisionError):
                fps = 30.0
        elif stream.get("codec_type") == "audio":
            has_audio = True
    duration = float(data.get("format", {}).get("duration", 0.0) or 0.0)
    return VideoMeta(width=width, height=height, duration_sec=duration, fps=fps, has_audio=has_audio)


def _build_video_filters(meta: VideoMeta, p: UniquifyParams) -> str:
    if meta.width <= 0 or meta.height <= 0:
        meta = VideoMeta(width=1080, height=1920, duration_sec=meta.duration_sec, fps=meta.fps, has_audio=meta.has_audio)
    crop_w = max(2, int(meta.width * (1 - (p.crop_left_pct + p.crop_right_pct) / 100.0)))
    crop_h = max(2, int(meta.height * (1 - (p.crop_top_pct + p.crop_bottom_pct) / 100.0)))
    crop_x = int(meta.width * p.crop_left_pct / 100.0)
    crop_y = int(meta.height * p.crop_top_pct / 100.0)
    crop_w -= crop_w % 2
    crop_h -= crop_h % 2

    filters = [
        f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}",
        f"scale={meta.width}:{meta.height}:flags=lanczos",
    ]
    if p.zoom and abs(p.zoom - 1.0) > 1e-3:
        zw = int((meta.width / p.zoom) // 2 * 2)
        zh = int((meta.height / p.zoom) // 2 * 2)
        zx = (meta.width - zw) // 2
        zy = (meta.height - zh) // 2
        filters.append(f"crop={zw}:{zh}:{zx}:{zy}")
        filters.append(f"scale={meta.width}:{meta.height}:flags=lanczos")

    # Watermark crop: blank the upper-right ~12 %×8 % rectangle and re-pad.
    # Helps wipe TikTok / CapCut watermarks that some sourced clips carry.
    if p.assume_tiktok_watermark:
        wm_w = max(2, int(meta.width * 0.12) // 2 * 2)
        wm_h = max(2, int(meta.height * 0.08) // 2 * 2)
        wm_x = max(0, meta.width - wm_w - 8)
        wm_y = 8
        # ``drawbox`` with ``fill=fill@1.0`` paints over the area; using a
        # neutral dark color matches typical Reels backgrounds and avoids the
        # giant white square artifact a naive pad would produce.
        filters.append(
            f"drawbox=x={wm_x}:y={wm_y}:w={wm_w}:h={wm_h}:color=black@0.85:t=fill"
        )

    if p.mirror:
        filters.append("hflip")

    eq_parts = []
    if abs(p.brightness) > 1e-4:
        eq_parts.append(f"brightness={p.brightness:.4f}")
    if abs(p.contrast - 1.0) > 1e-4:
        eq_parts.append(f"contrast={p.contrast:.4f}")
    if abs(p.saturation - 1.0) > 1e-4:
        eq_parts.append(f"saturation={p.saturation:.4f}")
    if abs(p.gamma - 1.0) > 1e-4:
        eq_parts.append(f"gamma={p.gamma:.4f}")
    if eq_parts:
        filters.append("eq=" + ":".join(eq_parts))

    # Resolution jitter: scale up by ``resolution_jitter_pct`` then back to
    # the original to give the encoder a slightly different sample grid.
    if p.resolution_jitter_pct and abs(p.resolution_jitter_pct - 1.0) > 1e-3:
        jw = max(2, int(meta.width * p.resolution_jitter_pct) // 2 * 2)
        jh = max(2, int(meta.height * p.resolution_jitter_pct) // 2 * 2)
        filters.append(f"scale={jw}:{jh}:flags=lanczos")
        filters.append(f"scale={meta.width}:{meta.height}:flags=lanczos")

    filters.append("format=yuv420p")
    return ",".join(filters)


def _build_audio_filters(p: UniquifyParams) -> str | None:
    parts: list[str] = []
    if abs(p.audio_atempo - 1.0) > 1e-4:
        parts.append(f"atempo={p.audio_atempo:.4f}")
    if abs(p.audio_pitch_cents) > 1e-4:
        ratio = 2 ** (p.audio_pitch_cents / 1200.0)
        parts.append(f"asetrate=44100*{ratio:.6f}")
        parts.append("aresample=44100")
        parts.append(f"atempo={1 / ratio:.6f}")
    if p.audio_eq_freq and abs(p.audio_eq_gain) > 1e-3:
        # Single-band parametric EQ — perturbs the audio fingerprint without
        # being audible to the listener.
        parts.append(
            f"equalizer=f={p.audio_eq_freq}:width_type=h:width=200:g={p.audio_eq_gain:.3f}"
        )
    if abs(p.audio_volume_db) > 1e-4:
        parts.append(f"volume={p.audio_volume_db:.4f}dB")
    return ",".join(parts) if parts else None


def uniquify(
    input_path: str | Path,
    output_path: str | Path,
    params: Optional[UniquifyParams] = None,
    *,
    allow_mirror: bool = False,
    rng: Optional[random.Random] = None,
    on_log: Optional[Callable[[str, str, str], None]] = None,
) -> UniquifyParams:
    """Re-encode ``input_path`` into ``output_path`` with random uniquification.

    Returns the params actually used (helpful for logging / reproducibility).
    """
    rng = rng or random.Random()
    src = Path(input_path)
    dst = Path(output_path)
    if not src.exists():
        raise FileNotFoundError(src)
    dst.parent.mkdir(parents=True, exist_ok=True)

    meta = probe(src)
    p = params or random_params(rng=rng, allow_mirror=allow_mirror)

    duration = max(0.0, meta.duration_sec - (p.trim_start_ms + p.trim_end_ms) / 1000.0)
    if duration <= 1.0:
        p.trim_start_ms = 0
        p.trim_end_ms = 0
        duration = meta.duration_sec

    vf = _build_video_filters(meta, p)
    af = _build_audio_filters(p)

    cmd: list[str] = [
        ffmpeg_bin(),
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-ss",
        f"{p.trim_start_ms / 1000:.3f}",
        "-i",
        str(src),
        "-t",
        f"{duration:.3f}",
        "-map_metadata",
        "-1",
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        p.preset,
        "-crf",
        str(p.crf),
        "-pix_fmt",
        "yuv420p",
        "-g",
        str(p.keyint),
        "-keyint_min",
        str(max(1, p.keyint // 2)),
        "-movflags",
        "+faststart",
        "-metadata",
        f"creation_time={p.creation_time_iso}",
        "-metadata",
        f"comment={secrets.token_hex(4)}",
    ]
    if meta.has_audio:
        cmd += ["-c:a", "aac", "-b:a", f"{p.audio_bitrate_kbps}k", "-ar", "44100"]
        if af:
            cmd += ["-af", af]
    else:
        cmd += ["-an"]

    cmd.append(str(dst))

    logger.info(
        "uniquify.start",
        src=str(src),
        dst=str(dst),
        crf=p.crf,
        preset=p.preset,
        mirror=p.mirror,
        zoom=round(p.zoom, 4),
        pitch_cents=round(p.audio_pitch_cents, 2),
    )
    if on_log is not None:
        on_log("info", "uniquify", f"Кодирование {src.name} -> {dst.name} (crf={p.crf})")
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
        tail = stderr[-2000:]
        logger.error("uniquify.ffmpeg_failed", returncode=exc.returncode, stderr=tail)
        if on_log is not None:
            on_log("error", "uniquify", f"Ошибка ffmpeg (код {exc.returncode}): {tail[-500:]}")
        raise

    logger.info("uniquify.done", dst=str(dst), size=dst.stat().st_size)
    if on_log is not None:
        on_log("info", "uniquify", f"Файл готов ({dst.stat().st_size} байт)")
    return p
