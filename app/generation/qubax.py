"""Qubax video generation for the factory render queue."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.db import SessionLocal
from app.generation.base import (
    INPUT_MODE_I2V,
    REF_START_IMAGE,
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
from app.generation.download import download_url
from app.generation.fal import aspect_ratio
from app.panel.settings_store import (
    resolve_qubax_api_key,
    resolve_qubax_api_public_base,
    resolve_qubax_default_model,
)
from app.services import qubax as qx
from app.services.qubax import extract_video_url, is_terminal_status
from app.services.http import client as http_client

def _resolve_key() -> str:
    db = SessionLocal()
    try:
        return resolve_qubax_api_key(db)
    finally:
        db.close()


class QubaxVideoBackend(VideoBackend):
    name = "qubax"
    model_licence = "Third-party models via Qubax"
    supports_i2v = True
    supports_v2v = False

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _api_key(self) -> str:
        key = (self.settings.qubax_api_key or "").strip() or _resolve_key()
        if not key:
            raise GenerationError("QUBAX_API_KEY не задан")
        return key

    def _model_for(self, request: GenerationRequest) -> str:
        db = SessionLocal()
        try:
            if request.mode == INPUT_MODE_I2V:
                return resolve_qubax_default_model(db, i2v=True)
            return resolve_qubax_default_model(db, i2v=False)
        finally:
            db.close()

    def estimate_cost(self, request: GenerationRequest) -> float:
        return 0.5 * max(1.0, request.duration_s / 5.0)

    def healthcheck(self) -> bool:
        try:
            return bool(_resolve_key() or (self.settings.qubax_api_key or "").strip())
        except Exception:
            return False

    def health_detail(self) -> str:
        if self.healthcheck():
            return ""
        return "Qubax не настроен — задайте API-ключ на странице Qubax или QUBAX_API_KEY"

    def _ref_image_path(self, request: GenerationRequest) -> Path | None:
        for ref in request.references:
            if ref.role == REF_START_IMAGE:
                return ref.path
        if request.references and request.mode == INPUT_MODE_I2V:
            return request.references[0].path
        return None

    def generate(
        self,
        request: GenerationRequest,
        out_dir: Path,
        on_progress: ProgressCallback | None = None,
    ) -> GenerationResult:
        api_key = self._api_key()
        model = self._model_for(request)
        report = on_progress or (lambda _: None)
        duration = qx.duration_token(request.duration_s)
        ratio = aspect_ratio(request.width, request.height)
        image_url: str | None = None
        if request.mode == INPUT_MODE_I2V:
            ref = self._ref_image_path(request)
            if ref is None:
                raise GenerationError("Qubax I2V: нужен start_image")
            db = SessionLocal()
            try:
                pub_base, _ = resolve_qubax_api_public_base(db)
                image_url = qx.public_reference_url(
                    ref.name, self.settings, public_base=pub_base or None
                )
            finally:
                db.close()
        try:
            remote = qx.create_video(
                api_key,
                model=model,
                prompt=request.prompt[:8000],
                duration=duration,
                aspect_ratio=ratio,
                image_url=image_url,
            )
        except qx.QubaxError as exc:
            raise GenerationError(str(exc), retryable=exc.status_code == 504) from exc

        report(Progress(STAGE_SUBMITTED))
        external = str(remote.get("id") or "")
        if not external:
            raise GenerationError("Qubax не вернул id задачи")

        body = self._await_result(api_key, external, report)
        video_url = extract_video_url(body)
        if not video_url:
            raise GenerationError("Qubax не вернул video_url")
        report(Progress(STAGE_DOWNLOADING))
        dest = out_dir / f"qubax-{external}.mp4"
        with http_client(self.settings, timeout=300) as client:
            path = download_url(client, str(video_url), dest, name="qubax")
        return GenerationResult(
            video_path=path,
            generator=model,
            cost_usd=self.estimate_cost(request),
            backend=self.name,
        )

    def _await_result(
        self,
        api_key: str,
        external_id: str,
        report: ProgressCallback,
    ) -> dict[str, Any]:
        import time

        deadline = time.monotonic() + self.settings.generation_timeout_seconds
        interval = self.settings.generation_poll_seconds
        while True:
            try:
                body = qx.get_video_job(api_key, external_id)
            except qx.QubaxError as exc:
                raise GenerationError(str(exc), retryable=True) from exc
            status = str(body.get("status") or "").lower()
            if not is_terminal_status(status):
                report(Progress(STAGE_RENDERING))
            if status == "completed":
                return body
            if is_terminal_status(status):
                err = body.get("error") or body.get("message") or status
                raise GenerationError(f"Qubax: {err}")
            if time.monotonic() > deadline:
                raise GenerationError(
                    f"Qubax не завершил {external_id} за {self.settings.generation_timeout_seconds:.0f}с",
                    retryable=True,
                )
            time.sleep(interval)
