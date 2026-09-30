"""Worker-side generation: resolve, budget, backends."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.config import settings
from app.db.models import AssetSource, GenerationJob, MediaAsset, PipelineStatus
from app.generation.base import (
    INPUT_MODE_I2V,
    INPUT_MODE_SLIDESHOW,
    GenerationResult,
    VideoBackend,
)
from app.services.generation import run_generation_job
from app.services.generation_inputs import apply_job_reference_fields
from tests.unit.test_chain import FakeEngine


class TextOnlyEngine(VideoBackend):
    name = "text_only_stub"
    model_licence = "test"
    supports_i2v = False
    supports_v2v = False

    def healthcheck(self) -> bool:
        return True

    def health_detail(self) -> str:
        return ""

    def generate(self, request, out_dir: Path, on_progress=None) -> GenerationResult:
        path = out_dir / "out.mp4"
        path.write_bytes(b"mp4")
        return GenerationResult(video_path=path, generator="stub", backend=self.name)


def test_slideshow_apply_sets_mode_backend_coerced_at_enqueue_or_worker():
    """apply_job_reference_fields only sets mode; API/tools set backend=slideshow on save."""
    job = GenerationJob(prompt="ken", backend="fal", status=PipelineStatus.queued)
    apply_job_reference_fields(
        job,
        input_mode=INPUT_MODE_SLIDESHOW,
        reference_filename="still.jpg",
    )
    assert job.input_mode == INPUT_MODE_SLIDESHOW
    assert job.backend == "fal"


def test_run_generation_job_slideshow_resolves_slideshow_backend(
    db_session, app_env, monkeypatch
):
    monkeypatch.setattr(
        "app.services.media.probe_video",
        lambda _path: type("P", (), {"duration_s": 5.0, "width": 720, "height": 1280})(),
    )
    ref = settings.video_source_dir / "still.jpg"
    ref.write_bytes(b"jpeg")
    job = GenerationJob(
        prompt="ken",
        backend="fal",
        status=PipelineStatus.queued,
        input_mode=INPUT_MODE_SLIDESHOW,
        reference_json=json.dumps([{"role": "start_image", "filename": "still.jpg"}]),
    )
    db_session.add(job)
    db_session.commit()
    resolved: list[str] = []

    def _track_get_backend(name, _settings):
        resolved.append(name)
        engine = FakeEngine("slideshow")
        engine.supports_slideshow = True
        return engine

    monkeypatch.setattr("app.services.generation.get_backend", _track_get_backend)
    run_generation_job(
        db_session,
        job,
        backend=FakeEngine("fal"),
        settings=settings,
    )
    db_session.refresh(job)
    assert resolved == ["slideshow"]
    assert job.status is PipelineStatus.done


def test_run_generation_resolve_failure_non_retryable(db_session, app_env):
    job = GenerationJob(
        prompt="animate",
        backend="auto",
        status=PipelineStatus.queued,
        reference_json=json.dumps([{"role": "start_image", "filename": "missing.jpg"}]),
    )
    db_session.add(job)
    db_session.commit()
    run_generation_job(db_session, job, backend=FakeEngine("stub"), settings=settings)
    db_session.refresh(job)
    assert job.status in (PipelineStatus.failed, PipelineStatus.dead)
    assert job.attempts == 0
    assert job.last_error


def test_run_generation_unsupported_backend_fails(db_session, app_env):
    ref = settings.video_source_dir / "ref.png"
    ref.write_bytes(b"png")
    job = GenerationJob(
        prompt="move",
        backend="text_only_stub",
        status=PipelineStatus.queued,
        input_mode=INPUT_MODE_I2V,
        reference_json=json.dumps([{"role": "start_image", "filename": "ref.png"}]),
    )
    db_session.add(job)
    db_session.commit()
    run_generation_job(
        db_session,
        job,
        backend=TextOnlyEngine(),
        settings=settings,
    )
    db_session.refresh(job)
    assert job.status in (PipelineStatus.failed, PipelineStatus.dead)
    assert "не поддерживает режим" in (job.last_error or "")
    assert job.attempts == 0


def test_run_generation_budget_defers_without_attempt(db_session, app_env, monkeypatch):
    job = GenerationJob(prompt="fog", backend="auto", status=PipelineStatus.queued, attempts=0)
    db_session.add(job)
    db_session.commit()
    now = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)

    def _refuse(*_args, **_kwargs):
        return "daily cap"

    monkeypatch.setattr("app.services.generation.refuses", _refuse)
    run_generation_job(
        db_session,
        job,
        backend=FakeEngine("cheap"),
        settings=settings,
        now=now,
    )
    db_session.refresh(job)
    assert job.status is PipelineStatus.queued
    assert job.attempts == 0
    assert "held until tomorrow" in (job.last_error or "")
    assert job.scheduled_at is not None
    scheduled = job.scheduled_at
    if scheduled.tzinfo is None:
        scheduled = scheduled.replace(tzinfo=timezone.utc)
    assert scheduled > now


def test_run_generation_success_creates_asset(db_session, app_env, monkeypatch):
    monkeypatch.setattr(
        "app.services.media.probe_video",
        lambda _path: type("P", (), {"duration_s": 5.0, "width": 720, "height": 1280})(),
    )
    job = GenerationJob(prompt="fog", backend="auto", status=PipelineStatus.queued)
    db_session.add(job)
    db_session.commit()
    run_generation_job(db_session, job, backend=FakeEngine("fal"), settings=settings)
    db_session.refresh(job)
    assert job.status is PipelineStatus.done
    assert job.asset_id is not None
    asset = db_session.get(MediaAsset, job.asset_id)
    assert asset is not None
    assert asset.source is AssetSource.generated
    assert asset.is_synthetic
    assert (settings.media_dir / asset.filename).is_file()


def test_ensure_video_reference_skips_short_clip(app_env, monkeypatch):
    from app.video.reference_trim import ensure_video_reference

    path = settings.video_source_dir / "short.mp4"
    path.write_bytes(b"fake")
    monkeypatch.setattr("app.video.reference_trim.clip_duration", lambda _p: 5.0)
    out = ensure_video_reference(path, settings, max_duration_s=15.0)
    assert out == path


def test_ensure_video_reference_trims_long_clip(app_env, monkeypatch, tmp_path):
    from app.video.reference_trim import ensure_video_reference

    path = settings.video_source_dir / "long.mp4"
    path.write_bytes(b"fake")
    trimmed = settings.media_dir / "_refs" / "trim-x.mp4"
    trimmed.parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("app.video.reference_trim.clip_duration", lambda _p: 30.0)

    def fake_run(cmd, **_kwargs):
        dest = Path(cmd[-1])
        dest.write_bytes(b"trimmed")

    monkeypatch.setattr("app.video.reference_trim.subprocess.run", fake_run)
    out = ensure_video_reference(path, settings, max_duration_s=15.0)
    assert out.name.startswith("trim-")
    assert out.is_file()
