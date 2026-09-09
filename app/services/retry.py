"""Putting a finished-but-failed job back in the queue."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from app.db.models import PipelineStatus, PostJobStatus

RETRIABLE_PIPELINE = (PipelineStatus.dead, PipelineStatus.failed, PipelineStatus.cancelled)
RETRIABLE_POST = (PostJobStatus.dead, PostJobStatus.failed, PostJobStatus.cancelled)


class RetriableJob(Protocol):
    status: object
    attempts: int
    last_error: str | None


class NotRetriable(ValueError):
    pass


def revive(job: RetriableJob, *, now: datetime | None = None) -> None:
    """Queue a stopped job again, as though it had never run."""
    status = job.status
    if status in RETRIABLE_PIPELINE:
        job.status = PipelineStatus.queued  # type: ignore[assignment]
        scheduled_at = now or datetime.now(timezone.utc)
        if hasattr(job, "scheduled_at"):
            job.scheduled_at = scheduled_at  # type: ignore[attr-defined]
    elif status in RETRIABLE_POST:
        job.status = PostJobStatus.queued  # type: ignore[assignment]
        if hasattr(job, "next_attempt_at"):
            job.next_attempt_at = None  # type: ignore[attr-defined]
    else:
        value = getattr(status, "value", status)
        raise NotRetriable(f"задачу в состоянии «{value}» повторить нельзя")

    job.attempts = 0
    job.last_error = None
    if hasattr(job, "stage"):
        job.stage = ""
        job.queue_position = None
