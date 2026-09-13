"""fal.ai video generation over its queue REST API.

Submit returns immediately with a request id; the render itself takes
minutes, so this backend polls the queue rather than holding one long
request open. The finished MP4 is downloaded from the URL fal returns.

Model and pricing default to Wan 2.5 text-to-video, billed per second of
output. `cost_usd` on the result is what that clip cost, so the operator
can see spend per asset instead of discovering it on an invoice.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.generation.base import (
    STAGE_DOWNLOADING,
    STAGE_QUEUED,
    STAGE_RENDERING,
    STAGE_SUBMITTED,
    GenerationError,
    GenerationRequest,
    GenerationResult,
    Progress,
    ProgressCallback,
    VideoBackend,
)
from app.generation.download import download_url, raise_http
from app.services.http import client as http_client

QUEUE_ROOT = "https://queue.fal.run"

#: fal accepts only these two clip lengths for Wan 2.5.
ALLOWED_DURATIONS = (5, 10)
ALLOWED_RESOLUTIONS = (480, 720, 1080)

#: USD per second of output, by model. Checked against fal's pricing page;
#: an unknown model reports 0.0 rather than inventing a number.
RATE_USD_PER_SECOND = {
    "fal-ai/wan-25-preview/text-to-video": 0.05,
    "fal-ai/kling-video/v2.5-turbo/pro/text-to-video": 0.07,
}

TERMINAL_FAILURES = {"FAILED", "ERROR", "CANCELLED"}


def _snap(value: float, allowed: tuple[int, ...]) -> int:
    return min(allowed, key=lambda option: abs(option - value))


def aspect_ratio(width: int, height: int) -> str:
    """Nearest ratio fal accepts for the requested frame."""
    if height == 0:
        raise GenerationError("height must be non-zero")
    ratio = width / height
    options = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0}
    return min(options, key=lambda name: abs(options[name] - ratio))


class FalVideoBackend(VideoBackend):
    name = "fal"
    # Wan 2.5 weights are Apache-2.0; fal hosts them as a paid service.
    model_licence = "Apache-2.0 (Wan 2.5), served by fal.ai"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.model = self.settings.fal_model

    # --- Contract ----------------------------------------------------

    def estimate_cost(self, request: GenerationRequest) -> float:
        """The same arithmetic the bill uses, done before the request."""
        return RATE_USD_PER_SECOND.get(self.model, 0.0) * request.duration_s

    def healthcheck(self) -> bool:
        return bool(self.settings.fal_api_key)

    def health_detail(self) -> str:
        if self.healthcheck():
            return ""
        return "fal не настроен — задайте его API-ключ"

    def generate(
        self,
        request: GenerationRequest,
        out_dir: Path,
        on_progress: ProgressCallback | None = None,
    ) -> GenerationResult:
        if not self.healthcheck():
            raise GenerationError("FAL_API_KEY is not set")

        report = on_progress or (lambda _: None)
        duration = _snap(request.duration_s, ALLOWED_DURATIONS)
        payload = self._payload(request, duration)

        with http_client(self.settings, timeout=60, headers=self._headers()) as client:
            request_id = self._submit(client, payload)
            report(Progress(STAGE_SUBMITTED))
            result = self._await_result(client, request_id, report)
            video_url = self._video_url(result)
            report(Progress(STAGE_DOWNLOADING))
            path = self._download(client, video_url, out_dir, request_id)

        return GenerationResult(
            video_path=path,
            generator=f"{self.model}",
            cost_usd=RATE_USD_PER_SECOND.get(self.model, 0.0) * duration,
            seed=result.get("seed"),
            backend=self.name,
        )

    # --- Queue -------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Key {self.settings.fal_api_key}"}

    def _payload(self, request: GenerationRequest, duration: int) -> dict[str, Any]:
        # fal names a resolution by the shorter side, whichever way up
        # the clip is.
        shortest = min(request.width, request.height)
        payload: dict[str, Any] = {
            "prompt": request.prompt[:1500],
            "duration": str(duration),
            "resolution": f"{_snap(shortest, ALLOWED_RESOLUTIONS)}p",
            "aspect_ratio": aspect_ratio(request.width, request.height),
        }
        if request.negative_prompt:
            payload["negative_prompt"] = request.negative_prompt[:500]
        if request.seed is not None:
            payload["seed"] = request.seed
        return payload

    def _submit(self, client: httpx.Client, payload: dict[str, Any]) -> str:
        response = client.post(f"{QUEUE_ROOT}/{self.model}", json=payload)
        raise_http(response, "fal", "submit")

        request_id = response.json().get("request_id")
        if not request_id:
            raise GenerationError("fal accepted the job but returned no request_id")
        return request_id

    def _await_result(
        self,
        client: httpx.Client,
        request_id: str,
        report: ProgressCallback = lambda _: None,
    ) -> dict[str, Any]:
        base = f"{QUEUE_ROOT}/{self.model}/requests/{request_id}"
        deadline = time.monotonic() + self.settings.generation_timeout_seconds

        while True:
            response = client.get(f"{base}/status")
            raise_http(response, "fal", "status")
            body = response.json()
            status = body.get("status")

            # fal tells us where we are in its queue; passing that on is
            # the difference between "running" and "third in line".
            if status == "IN_QUEUE":
                report(
                    Progress(STAGE_QUEUED, queue_position=body.get("queue_position"))
                )
            elif status == "IN_PROGRESS":
                report(Progress(STAGE_RENDERING))

            if status == "COMPLETED":
                break
            if status in TERMINAL_FAILURES:
                raise GenerationError(f"fal reported {status} for {request_id}")
            if time.monotonic() > deadline:
                raise GenerationError(
                    f"fal did not finish {request_id} within "
                    f"{self.settings.generation_timeout_seconds:.0f}s",
                    retryable=True,
                )
            time.sleep(self.settings.generation_poll_seconds)

        result = client.get(base)
        raise_http(result, "fal", "result")
        return result.json()

    @staticmethod
    def _video_url(result: dict[str, Any]) -> str:
        url = (result.get("video") or {}).get("url")
        if not url:
            raise GenerationError("fal returned no video url")
        return url

    def _download(
        self, client: httpx.Client, url: str, out_dir: Path, request_id: str
    ) -> Path:
        destination = out_dir / f"fal-{request_id}.mp4"
        return download_url(client, url, destination, name="fal")
