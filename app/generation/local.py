"""Self-hosted Wan / Comfy-style HTTP text-to-video."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import httpx

from app.config import Settings, get_settings
import base64

from app.generation.base import (
    INPUT_MODE_I2V,
    INPUT_MODE_V2V,
    REF_MOTION_VIDEO,
    REF_START_IMAGE,
    STAGE_DOWNLOADING,
    STAGE_QUEUED,
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
from app.generation.download import raise_http, save_response
from app.services.gateway_probe import wan_reachable
from app.services.gpu_slot import hold_for_video
from app.services.http import client as http_client
from app.services import runtime
from app.services.salad_idle import touch


class LocalVideoBackend(VideoBackend):
    name = "local"
    model_licence = "Apache-2.0 (self-hosted Wan / LTX)"
    supports_i2v = True
    supports_v2v = True

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def healthcheck(self) -> bool:
        # 2xx = health page; 405 = POST-only /generate is up. Cached with the GPU card.
        return bool(wan_reachable(self.settings))

    def health_detail(self) -> str:
        if self.healthcheck():
            return ""
        if not (self.settings.wan_base_url or "").strip():
            return "local не настроен — задайте WAN_BASE_URL"
        return "Wan не отвечает по WAN_BASE_URL"

    def generate(
        self,
        request: GenerationRequest,
        out_dir: Path,
        on_progress: ProgressCallback | None = None,
    ) -> GenerationResult:
        if not self.healthcheck():
            raise GenerationError(self.health_detail())
        touch(self.settings)
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
        if request.mode == INPUT_MODE_I2V:
            ref = next((r for r in request.references if r.role == REF_START_IMAGE), None)
            if ref is None and request.references:
                ref = request.references[0]
            if ref is None:
                raise GenerationError("local I2V: нужен image reference")
            payload["image_base64"] = base64.b64encode(ref.path.read_bytes()).decode("ascii")
            payload["image_mime"] = ref.mime
        elif request.mode == INPUT_MODE_V2V:
            ref = next((r for r in request.references if r.role == REF_MOTION_VIDEO), None)
            if ref is None:
                raise GenerationError("local V2V: нужен motion_video")
            payload["video_base64"] = base64.b64encode(ref.path.read_bytes()).decode("ascii")
            payload["video_mime"] = ref.mime
        destination = out_dir / f"local-{uuid.uuid4().hex}.mp4"
        url = self.settings.wan_base_url.rstrip("/")
        try:
            with hold_for_video(self.settings):
                report(Progress(STAGE_UNLOADING))
                runtime.unload_loaded(self.settings)
                if self._wan_async():
                    with http_client(self.settings, timeout=60.0, headers=headers) as client:
                        path = self._generate_async(client, url, payload, destination, report)
                else:
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

    def _wan_async(self) -> bool:
        if self.settings.wan_async:
            return True
        return "salad.cloud" in (self.settings.wan_base_url or "").lower()

    def _busy_step(self) -> float:
        poll = float(self.settings.generation_poll_seconds)
        if poll < 5:
            return max(0.0, poll)
        return 15.0

    def _generate_async(
        self,
        client: httpx.Client,
        url: str,
        payload: dict,
        destination: Path,
        report: ProgressCallback,
    ) -> Path:
        """Submit, poll, download. Each HTTP call stays well under Salad's ~100s cut."""
        base = url
        tried_suffix = url.rstrip("/").endswith("/generate")
        deadline = time.monotonic() + float(self.settings.generation_timeout_seconds)
        step = self._busy_step()
        while True:
            response = client.post(base, json=payload, headers={"X-Async": "1"})
            if response.status_code == 404 and not tried_suffix:
                base = f"{url}/generate"
                tried_suffix = True
                continue
            if response.status_code == 202:
                return self._accept_job(client, base, response, destination, report)
            if response.status_code == 200:
                return self._accept_immediate(client, base, response, destination, report)
            if response.status_code == 409:
                if time.monotonic() >= deadline:
                    raise GenerationError(
                        "local: GPU занята другим рендером. "
                        "Дождитесь его или сделайте Stop/Start группы Salad.",
                        retryable=True,
                    )
                report(Progress(STAGE_QUEUED))
                touch(self.settings)
                time.sleep(step)
                continue
            raise_http(response, self.name, "generate")
            raise GenerationError("local: async generate не вернул 202", retryable=True)

    def _accept_job(
        self,
        client: httpx.Client,
        base: str,
        response: httpx.Response,
        destination: Path,
        report: ProgressCallback,
    ) -> Path:
        try:
            body = response.json()
        except ValueError as exc:
            raise GenerationError("local: async generate вернул не JSON", retryable=True) from exc
        job_id = str((body or {}).get("job_id") or "").strip()
        if not job_id:
            raise GenerationError("local: async generate без job_id", retryable=True)
        return self._poll_job(client, base, job_id, destination, report)

    def _accept_immediate(
        self,
        client: httpx.Client,
        base: str,
        response: httpx.Response,
        destination: Path,
        report: ProgressCallback,
    ) -> Path:
        job_id = ""
        ctype = (response.headers.get("content-type") or "").lower()
        if "json" in ctype or response.content[:1] == b"{":
            try:
                body = response.json()
            except ValueError:
                body = None
            if isinstance(body, dict):
                job_id = str(body.get("job_id") or "").strip()
        if job_id:
            return self._poll_job(client, base, job_id, destination, report)
        if "salad.cloud" in base.lower():
            raise GenerationError(
                "local: образ GPU без async API — пересоберите salad-gpu и сделайте Stop/Start группы Salad",
                retryable=False,
            )
        report(Progress(STAGE_DOWNLOADING))
        return save_response(client, response, destination, name=self.name)

    def _poll_job(
        self,
        client: httpx.Client,
        base: str,
        job_id: str,
        destination: Path,
        report: ProgressCallback,
    ) -> Path:
        deadline = time.monotonic() + float(self.settings.generation_timeout_seconds)
        interval = max(0.0, float(self.settings.generation_poll_seconds))
        last_touch = time.monotonic()
        status_url = f"{base}/jobs/{job_id}"
        while True:
            if time.monotonic() > deadline:
                raise GenerationError("local: таймаут ожидания Wan", retryable=True)
            response = client.get(status_url)
            if response.status_code == 524:
                time.sleep(interval)
                continue
            if response.status_code >= 400:
                raise_http(response, self.name, "status")
            try:
                body = response.json()
            except ValueError as exc:
                raise GenerationError("local: статус Wan не JSON", retryable=True) from exc
            status = str((body or {}).get("status") or "")
            report(Progress(STAGE_RENDERING))
            now = time.monotonic()
            if now - last_touch >= 30:
                touch(self.settings)
                last_touch = now
            if status == "failed":
                err = str((body or {}).get("error") or "wan failed").strip() or "wan failed"
                raise GenerationError(f"local: {err}", retryable=True)
            if status == "done":
                report(Progress(STAGE_DOWNLOADING))
                while True:
                    if time.monotonic() > deadline:
                        raise GenerationError("local: таймаут ожидания Wan", retryable=True)
                    file_response = client.get(f"{base}/jobs/{job_id}/file")
                    if file_response.status_code == 409:
                        time.sleep(interval)
                        continue
                    return save_response(client, file_response, destination, name=self.name)
            time.sleep(interval)
