"""Split a long local Wan job into short T2V segments and soft-join them.

Salad only hosts Wan 2.1 T2V 1.3B (5 or 10 s per pass). Longer clips are
several of those passes with a shared seed, a continuation prompt, and an
xfade — not a single 60-second Wan run.
"""

from __future__ import annotations

import random
from pathlib import Path

from app.generation.base import GenerationRequest
from app.video.compose import ComposeError, ComposeRequest, compose

SEGMENT_CAP_S = 10.0
SEGMENT_SHORT_S = 5.0
MAX_TOTAL_S = 60.0
VIDEO_FADE_S = 0.5

CONTINUATION_TAIL = (
    "Same subject, setting, lighting, color palette, and camera language. "
    "Smooth continuation of the action — do not restart the scene, "
    "do not change wardrobe or location."
)


def segment_durations(total_s: float) -> list[float]:
    """Break a long request into Wan-sized pieces (5 or 10 seconds)."""
    total = max(SEGMENT_SHORT_S, min(float(total_s), MAX_TOTAL_S))
    if total <= SEGMENT_CAP_S:
        return [SEGMENT_CAP_S if total >= 7.5 else SEGMENT_SHORT_S]
    chunks: list[float] = []
    remaining = total
    while remaining > SEGMENT_CAP_S + 0.01:
        chunks.append(SEGMENT_CAP_S)
        remaining -= SEGMENT_CAP_S
    if remaining >= 7.5:
        chunks.append(SEGMENT_CAP_S)
    elif remaining >= SEGMENT_SHORT_S - 0.01:
        chunks.append(SEGMENT_SHORT_S)
    elif chunks:
        # Fold a tiny remainder into the previous 10 s chunk (Wan snaps anyway).
        pass
    else:
        chunks.append(SEGMENT_SHORT_S)
    return chunks


def continuation_prompt(base: str, index: int, count: int, total_s: float) -> str:
    """Keep style locked across segments; Wan still only sees text."""
    scene = (base or "").strip()
    marker = (
        f"[Segment {index}/{count} of a continuous {int(round(total_s))}s take. "
        f"{CONTINUATION_TAIL}]"
    )
    if not scene:
        return marker[:1500]
    joined = f"{scene}\n\n{marker}"
    return joined[:1500]


def shared_seed(request: GenerationRequest) -> int:
    if request.seed is not None:
        return int(request.seed)
    return random.randint(0, 2_147_483_647)


def segment_request(
    request: GenerationRequest,
    *,
    duration_s: float,
    prompt: str,
    seed: int,
) -> GenerationRequest:
    return GenerationRequest(
        prompt=prompt,
        negative_prompt=request.negative_prompt,
        width=request.width,
        height=request.height,
        duration_s=duration_s,
        seed=seed,
        mode=request.mode,
        references=list(request.references),
    )


def stitch_segments(
    clips: list[Path],
    output: Path,
    *,
    width: int,
    height: int,
    fade_s: float = VIDEO_FADE_S,
    clip_durations: list[float] | None = None,
) -> Path:
    if len(clips) == 1:
        if clips[0].resolve() != output.resolve():
            output.write_bytes(clips[0].read_bytes())
        return output
    try:
        return compose(
            ComposeRequest(
                clips=clips,
                output=output,
                width=width,
                height=height,
                video_fade_s=fade_s,
                clip_durations=clip_durations,
            )
        )
    except ComposeError as exc:
        from app.generation.base import GenerationError

        raise GenerationError(f"local: склейка сегментов: {exc}", retryable=False) from exc


def stage_label(index: int, count: int) -> str:
    return f"сегмент {index}/{count} · рендер"
