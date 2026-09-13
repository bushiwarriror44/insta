"""Optional Hugging Face Space (Gradio) text-to-video. Experimental last resort."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import httpx

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
from app.generation.download import download_url, raise_http, video_url_from
from app.services.http import client as http_client


class HfSpaceVideoBackend(VideoBackend):
    name = "hfspace"
    model_licence = "depends on the Space"
    experimental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def healthcheck(self) -> bool:
        return bool(self.settings.hf_space_id)

    def health_detail(self) -> str:
        if self.healthcheck():
            return ""
        return "hfspace выключен — задайте HF_SPACE_ID"

    def generate(
        self,
        request: GenerationRequest,
        out_dir: Path,
        on_progress: ProgressCallback | None = None,
    ) -> GenerationResult:
        if not self.healthcheck():
            raise GenerationError(self.health_detail(), retryable=True)
        report = on_progress or (lambda _: None)
        report(Progress(STAGE_SUBMITTED))
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.settings.hf_token:
            headers["Authorization"] = f"Bearer {self.settings.hf_token}"
        destination = out_dir / f"hfspace-{uuid.uuid4().hex}.mp4"
        try:
            with http_client(
                self.settings,
                timeout=self.settings.generation_timeout_seconds,
                headers=headers,
            ) as client:
                event_id = self._submit(client, request)
                report(Progress(STAGE_QUEUED))
                url = self._await_url(client, event_id, report)
                report(Progress(STAGE_DOWNLOADING))
                path = download_url(client, url, destination, name=self.name)
        except httpx.RequestError as exc:
            raise GenerationError(f"hfspace: {exc}", retryable=True) from exc
        return GenerationResult(
            video_path=path,
            generator=self.settings.hf_space_id,
            backend=self.name,
        )

    def _host(self) -> str:
        slug = self.settings.hf_space_id.strip().replace("/", "-").replace("_", "-")
        return f"https://{slug}.hf.space"

    def _call_root(self) -> str:
        api = self.settings.hf_space_api_name.strip() or "predict"
        return f"{self._host()}/gradio_api/call/{api}"

    def _submit(self, client: httpx.Client, request: GenerationRequest) -> str:
        response = client.post(self._call_root(), json={"data": [request.prompt[:1500]]})
        raise_http(response, self.name, "submit")
        try:
            body = response.json()
        except ValueError as exc:
            raise GenerationError("hfspace returned invalid JSON", retryable=True) from exc
        event_id = body.get("event_id") or body.get("eventId")
        if not event_id:
            raise GenerationError("hfspace returned no event_id", retryable=True)
        return str(event_id)

    def _await_url(
        self,
        client: httpx.Client,
        event_id: str,
        report: ProgressCallback,
    ) -> str:
        deadline = time.monotonic() + self.settings.generation_timeout_seconds
        url = f"{self._call_root()}/{event_id}"
        while True:
            response = client.get(url)
            raise_http(response, self.name, "status")
            report(Progress(STAGE_RENDERING))
            found = _video_from_gradio(response.text)
            if found:
                return found
            if time.monotonic() > deadline:
                raise GenerationError(
                    f"hfspace did not finish within {self.settings.generation_timeout_seconds:.0f}s",
                    retryable=True,
                )
            time.sleep(self.settings.generation_poll_seconds)


def _video_from_gradio(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("data:"):
            stripped = stripped[5:].strip()
        if not stripped or stripped == "[DONE]":
            continue
        try:
            body = json.loads(stripped)
        except ValueError:
            continue
        if isinstance(body, dict) and body.get("msg") in {"process_completed", "complete"}:
            output = body.get("output") or body
            nested = output.get("data") if isinstance(output, dict) else None
            url = _first_http(nested if nested is not None else output)
            if url:
                return url
        url = video_url_from(body) if isinstance(body, dict) else ""
        if url:
            return url
        url = _first_http(body)
        if url:
            return url
    return ""


def _first_http(value: object) -> str:
    if isinstance(value, str) and value.startswith("http"):
        return value
    if isinstance(value, dict):
        url = video_url_from(value)
        if url:
            return url
        for item in value.values():
            found = _first_http(item)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _first_http(item)
            if found:
                return found
    return ""
