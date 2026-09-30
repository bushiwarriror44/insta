"""Contract for text-to-video backends.

Backends are swappable by config so the cost model is a deployment
decision, not an architectural one: self-hosted open-weight models on
your own or rented hardware, a provider's free tier, or a paid API all
sit behind this interface.

Only backends whose licence permits commercial use and whose access is
issued to you directly belong here. Pooled or resold keys for someone
else's paid service are not a backend.
"""

from __future__ import annotations

import abc
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

INPUT_MODE_TEXT = "text_only"
INPUT_MODE_I2V = "image_to_video"
INPUT_MODE_V2V = "video_to_video"
INPUT_MODE_SLIDESHOW = "image_slideshow"

REF_START_IMAGE = "start_image"
REF_END_IMAGE = "end_image"
REF_MOTION_VIDEO = "motion_video"
REF_STYLE_IMAGE = "style_image"


class GenerationError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(slots=True)
class GenerationReference:
    role: str
    path: Path
    mime: str


@dataclass(slots=True)
class GenerationRequest:
    prompt: str
    duration_s: float = 5.0
    width: int = 720
    height: int = 1280
    seed: int | None = None
    negative_prompt: str = ""
    mode: str = INPUT_MODE_TEXT
    references: list[GenerationReference] = field(default_factory=list)


#: Stages a render passes through, in order. Named for what the operator
#: is waiting on rather than for the provider's own vocabulary.
STAGE_SUBMITTED = "submitted"
STAGE_QUEUED = "waiting at the provider"
STAGE_UNLOADING = "unloading chat"
STAGE_RENDERING = "rendering"
STAGE_DOWNLOADING = "downloading"


@dataclass(slots=True)
class Progress:
    """Where a render has got to, while it is still running."""

    stage: str
    #: Place in the provider's queue, when it tells us one.
    queue_position: int | None = None


#: Called by a backend as a render advances. Reporting is best-effort:
#: a backend that cannot say where it is simply never calls it.
ProgressCallback = Callable[[Progress], None]


@dataclass(slots=True)
class GenerationResult:
    video_path: Path
    #: Recorded on the Asset so every platform upload can disclose it.
    generator: str
    #: Marginal cost of this clip in USD; 0.0 for self-hosted.
    cost_usd: float = 0.0
    seed: int | None = None
    #: Registry name that actually produced the file (for `auto` failover).
    backend: str = ""


class VideoBackend(abc.ABC):
    name: str
    #: Licence of the underlying model, e.g. "Apache-2.0". Commercial use
    #: of a non-commercial model is the operator's problem to avoid, so
    #: it is surfaced rather than buried in a provider's docs.
    model_licence: str
    experimental: bool = False
    supports_text: bool = True
    supports_i2v: bool = False
    supports_v2v: bool = False
    supports_slideshow: bool = False

    def health_detail(self) -> str:
        """Why `healthcheck` is false, or empty when the backend is ready."""
        if self.healthcheck():
            return ""
        return f"{self.name} не настроен — задайте его API-ключ"

    @abc.abstractmethod
    def generate(
        self,
        request: GenerationRequest,
        out_dir: Path,
        on_progress: ProgressCallback | None = None,
    ) -> GenerationResult:
        """Render one clip and return the file it wrote.

        `on_progress` may be called any number of times while the render
        runs, so the panel can say what it is waiting on instead of
        showing a minute of silence.
        """

    def estimate_cost(self, request: GenerationRequest) -> float:
        """What this render will cost, before it is paid for.

        A ceiling that could only be checked afterwards would not be a
        ceiling. Backends that cost nothing — anything self-hosted —
        inherit this and report zero, which is the truth for them.
        """
        return 0.0

    @abc.abstractmethod
    def healthcheck(self) -> bool:
        """True when the backend is reachable and configured."""
