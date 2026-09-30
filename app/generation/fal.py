"""fal.ai video generation over its queue REST API."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.generation.base import (
    INPUT_MODE_I2V,
    INPUT_MODE_V2V,
    REF_END_IMAGE,
    REF_MOTION_VIDEO,
    REF_START_IMAGE,
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
FAL_STORAGE_UPLOAD = "https://rest.alpha.fal.ai/storage/upload"

ALLOWED_DURATIONS = (5, 10)
ALLOWED_RESOLUTIONS = (480, 720, 1080)

RATE_USD_PER_SECOND = {
    "fal-ai/wan-25-preview/text-to-video": 0.05,
    "fal-ai/wan-25-preview/image-to-video": 0.05,
    "fal-ai/kling-video/v2.5-turbo/pro/text-to-video": 0.07,
}

TERMINAL_FAILURES = {"FAILED", "ERROR", "CANCELLED"}


def _snap(value: float, allowed: tuple[int, ...]) -> int:
    return min(allowed, key=lambda option: abs(option - value))


def aspect_ratio(width: int, height: int) -> str:
    if height == 0:
        raise GenerationError("height must be non-zero")
    ratio = width / height
    options = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0}
    return min(options, key=lambda name: abs(options[name] - ratio))


def _ref_by_role(request: GenerationRequest, role: str):
    for ref in request.references:
        if ref.role == role:
            return ref
    return None


class FalVideoBackend(VideoBackend):
    name = "fal"
    model_licence = "Apache-2.0 (Wan 2.5), served by fal.ai"
    supports_i2v = True
    supports_v2v = True

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.model = self.settings.fal_model

    def _active_model(self, request: GenerationRequest) -> str:
        if request.mode == INPUT_MODE_I2V:
            return (self.settings.fal_model_i2v or "").strip() or "fal-ai/wan-25-preview/image-to-video"
        if request.mode == INPUT_MODE_V2V:
            return (self.settings.fal_model_v2v or "").strip() or self.settings.fal_model
        return self.settings.fal_model

    def estimate_cost(self, request: GenerationRequest) -> float:
        model = self._active_model(request)
        return RATE_USD_PER_SECOND.get(model, 0.0) * request.duration_s

    def healthcheck(self) -> bool:
        return bool(self.settings.fal_api_key)

    def health_detail(self) -> str:
        if self.healthcheck():
            return ""
        return "fal не настроен — задайте его API-ключ"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Key {self.settings.fal_api_key}"}

    def _upload_file(self, client: httpx.Client, path: Path, mime: str) -> str:
        with path.open("rb") as handle:
            response = client.post(
                FAL_STORAGE_UPLOAD,
                headers=self._headers(),
                files={"file": (path.name, handle, mime)},
            )
        raise_http(response, "fal", "upload")
        body = response.json()
        url = body.get("file_url") or body.get("url")
        if not url:
            raise GenerationError("fal upload: нет url в ответе")
        return str(url)

    def _payload(self, request: GenerationRequest, duration: int, model: str) -> dict[str, Any]:
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

    def _payload_with_media(
        self,
        client: httpx.Client,
        request: GenerationRequest,
        duration: int,
        model: str,
    ) -> dict[str, Any]:
        payload = self._payload(request, duration, model)
        if request.mode == INPUT_MODE_I2V:
            ref = _ref_by_role(request, REF_START_IMAGE) or request.references[0]
            payload["image_url"] = self._upload_file(client, ref.path, ref.mime)
            end = _ref_by_role(request, REF_END_IMAGE)
            if end is not None:
                payload["end_image_url"] = self._upload_file(client, end.path, end.mime)
        elif request.mode == INPUT_MODE_V2V:
            ref = _ref_by_role(request, REF_MOTION_VIDEO)
            if ref is None:
                raise GenerationError("fal V2V: motion_video отсутствует")
            payload["video_url"] = self._upload_file(client, ref.path, ref.mime)
        return payload

    def _submit(self, client: httpx.Client, payload: dict[str, Any], model: str) -> str:
        response = client.post(f"{QUEUE_ROOT}/{model}", json=payload)
        raise_http(response, "fal", "submit")
        request_id = response.json().get("request_id")
        if not request_id:
            raise GenerationError("fal accepted the job but returned no request_id")
        return request_id

    def generate(
        self,
        request: GenerationRequest,
        out_dir: Path,
        on_progress: ProgressCallback | None = None,
    ) -> GenerationResult:
        if not self.healthcheck():
            raise GenerationError("FAL_API_KEY is not set")
        if request.mode == INPUT_MODE_I2V and not request.references:
            raise GenerationError("fal I2V: нужен start_image")
        if request.mode == INPUT_MODE_V2V and _ref_by_role(request, REF_MOTION_VIDEO) is None:
            raise GenerationError("fal V2V: нужен motion_video")

        report = on_progress or (lambda _: None)
        duration = _snap(request.duration_s, ALLOWED_DURATIONS)
        model = self._active_model(request)

        with http_client(self.settings, timeout=120, headers=self._headers()) as client:
            payload = self._payload(request, duration, model)
            if request.mode in (INPUT_MODE_I2V, INPUT_MODE_V2V):
                payload = self._payload_with_media(client, request, duration, model)
            request_id = self._submit(client, payload, model)
            report(Progress(STAGE_SUBMITTED))
            result = self._await_result(client, request_id, model, report)
            video_url = self._video_url(result)
            report(Progress(STAGE_DOWNLOADING))
            path = self._download(client, video_url, out_dir, request_id)

        return GenerationResult(
            video_path=path,
            generator=model,
            cost_usd=RATE_USD_PER_SECOND.get(model, 0.0) * duration,
            seed=result.get("seed"),
            backend=self.name,
        )

    def _await_result(
        self,
        client: httpx.Client,
        request_id: str,
        model: str,
        report: ProgressCallback = lambda _: None,
    ) -> dict[str, Any]:
        base = f"{QUEUE_ROOT}/{model}/requests/{request_id}"
        deadline = time.monotonic() + self.settings.generation_timeout_seconds

        while True:
            response = client.get(f"{base}/status")
            raise_http(response, "fal", "status")
            body = response.json()
            status = body.get("status")

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
