"""Hugging Face Inference Providers text-to-video."""

from __future__ import annotations

import uuid
from pathlib import Path

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


class HuggingFaceVideoBackend(VideoBackend):
    name = "huggingface"
    model_licence = "Apache-2.0 (Wan / LTX), served by Hugging Face"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def healthcheck(self) -> bool:
        return bool(self.settings.hf_token)

    def health_detail(self) -> str:
        if self.healthcheck():
            return ""
        return "huggingface не настроен — задайте HF_TOKEN"

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
        url = self._url()
        headers = {
            "Authorization": f"Bearer {self.settings.hf_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "inputs": request.prompt[:1500],
            "parameters": {
                "negative_prompt": request.negative_prompt[:500],
                "num_frames": max(1, int(request.duration_s * 8)),
                "width": request.width,
                "height": request.height,
            },
        }
        if request.seed is not None:
            payload["parameters"]["seed"] = request.seed
        destination = out_dir / f"hf-{uuid.uuid4().hex}.mp4"
        try:
            with http_client(self.settings, timeout=self.settings.generation_timeout_seconds, headers=headers) as client:
                report(Progress(STAGE_RENDERING))
                response = client.post(url, json=payload)
                report(Progress(STAGE_DOWNLOADING))
                path = save_response(client, response, destination, name=self.name)
        except httpx.RequestError as exc:
            raise GenerationError(f"huggingface: {exc}", retryable=True) from exc
        return GenerationResult(
            video_path=path,
            generator=self.settings.hf_video_model,
            backend=self.name,
        )

    def _url(self) -> str:
        root = self.settings.hf_inference_url.rstrip("/")
        model = self.settings.hf_video_model.strip("/")
        return f"{root}/hf-inference/models/{model}"
