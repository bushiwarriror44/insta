"""Pollinations public text-to-video HTTP."""

from __future__ import annotations

import uuid
from pathlib import Path
from urllib.parse import quote

import httpx

from app.config import Settings, get_settings
from app.generation.base import (
    STAGE_DOWNLOADING,
    STAGE_RENDERING,
    STAGE_SUBMITTED,
    GenerationError,
    GenerationRequest,
    GenerationResult,
    Progress,
    ProgressCallback,
    VideoBackend,
)
from app.generation.download import save_response
from app.services.http import client as http_client


class PollinationsVideoBackend(VideoBackend):
    name = "pollinations"
    model_licence = "varies (Pollinations public API)"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def healthcheck(self) -> bool:
        return bool(self.settings.pollinations_video_url)

    def health_detail(self) -> str:
        if self.healthcheck():
            return ""
        return "pollinations выключен — задайте POLLINATIONS_VIDEO_URL"

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
        headers: dict[str, str] = {}
        if self.settings.pollinations_api_key:
            headers["Authorization"] = f"Bearer {self.settings.pollinations_api_key}"
        destination = out_dir / f"pollinations-{uuid.uuid4().hex}.mp4"
        root = self.settings.pollinations_video_url.rstrip("/")
        try:
            with http_client(
                self.settings,
                timeout=self.settings.generation_timeout_seconds,
                headers=headers,
            ) as client:
                report(Progress(STAGE_RENDERING))
                response = self._call(client, root, request)
                report(Progress(STAGE_DOWNLOADING))
                path = save_response(client, response, destination, name=self.name)
        except httpx.RequestError as exc:
            raise GenerationError(f"pollinations: {exc}", retryable=True) from exc
        return GenerationResult(
            video_path=path,
            generator="pollinations",
            backend=self.name,
        )

    @staticmethod
    def _call(client: httpx.Client, root: str, request: GenerationRequest) -> httpx.Response:
        payload = {
            "prompt": request.prompt[:1500],
            "duration": request.duration_s,
            "width": request.width,
            "height": request.height,
        }
        if request.negative_prompt:
            payload["negative_prompt"] = request.negative_prompt[:500]
        if request.seed is not None:
            payload["seed"] = request.seed
        posted = client.post(root, json=payload)
        if posted.status_code not in (404, 405):
            return posted
        encoded = quote(request.prompt[:400], safe="")
        return client.get(
            f"{root}/{encoded}",
            params={"duration": request.duration_s, "width": request.width, "height": request.height},
        )
