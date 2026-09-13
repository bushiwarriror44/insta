"""Self-hosted Wan / Comfy-style HTTP text-to-video."""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx

from app.config import Settings, get_settings
from app.generation.base import (
    STAGE_DOWNLOADING,
    STAGE_RENDERING,
    STAGE_SUBMITTED,
    STAGE_UNLOADING,
    GenerationError,
    GenerationRequest,
    GenerationResult,
    Progress,
    ProgressCallback,
    VideoBackend,
)
from app.generation.download import save_response
from app.services.gpu_slot import hold_for_video
from app.services.http import client as http_client
from app.services import runtime


class LocalVideoBackend(VideoBackend):
    name = "local"
    model_licence = "Apache-2.0 (self-hosted Wan / LTX)"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def healthcheck(self) -> bool:
        return bool(self.settings.wan_base_url)

    def health_detail(self) -> str:
        if self.healthcheck():
            return ""
        return "local не настроен — задайте WAN_BASE_URL"

    def generate(
        self,
        request: GenerationRequest,
        out_dir: Path,
        on_progress: ProgressCallback | None = None,
    ) -> GenerationResult:
        if not self.healthcheck():
            raise GenerationError(self.health_detail())
        report = on_progress or (lambda _: None)
        report(Progress(STAGE_SUBMITTED))
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.settings.wan_api_key:
            headers["Authorization"] = f"Bearer {self.settings.wan_api_key}"
        payload = {
            "prompt": request.prompt[:1500],
            "negative_prompt": request.negative_prompt[:500],
            "duration_s": request.duration_s,
            "width": request.width,
            "height": request.height,
        }
        if request.seed is not None:
            payload["seed"] = request.seed
        destination = out_dir / f"local-{uuid.uuid4().hex}.mp4"
        url = self.settings.wan_base_url.rstrip("/")
        try:
            with hold_for_video(self.settings):
                report(Progress(STAGE_UNLOADING))
                runtime.unload_loaded(self.settings)
                with http_client(
                    self.settings,
                    timeout=self.settings.generation_timeout_seconds,
                    headers=headers,
                ) as client:
                    report(Progress(STAGE_RENDERING))
                    response = client.post(url, json=payload)
                    if response.status_code == 404:
                        response = client.post(f"{url}/generate", json=payload)
                    report(Progress(STAGE_DOWNLOADING))
                    path = save_response(client, response, destination, name=self.name)
        except httpx.RequestError as exc:
            raise GenerationError(f"local: {exc}", retryable=True) from exc
        return GenerationResult(
            video_path=path,
            generator="local",
            backend=self.name,
        )
