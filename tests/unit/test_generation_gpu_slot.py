"""Generation worker vs gpu_slot exclusivity."""

from __future__ import annotations

from app.config import settings
from app.db.models import GenerationJob, PipelineStatus
from app.services import gpu_slot
from app.services.generation import run_generation_job


def test_run_generation_job_retries_when_gpu_slot_held(db_session, app_env, monkeypatch):
    monkeypatch.setattr(settings, "wan_base_url", "http://gpu.example/generate", raising=True)
    job = GenerationJob(
        prompt="misty forest",
        backend="local",
        status=PipelineStatus.queued,
        attempts=0,
    )
    db_session.add(job)
    db_session.commit()

    with gpu_slot.hold_for_video(settings):
        run_generation_job(db_session, job, settings=settings)

    db_session.refresh(job)
    assert job.status is PipelineStatus.queued
    assert job.attempts == 1
    assert "занята" in (job.last_error or "").lower() or "GPU" in (job.last_error or "")
