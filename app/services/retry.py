"""Putting a finished-but-failed job back in the queue."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
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


def ensure_post_source(path: str) -> None:
    """Reject a publish retry when the source clip is no longer on disk."""
    file = Path(path or "")
    if not file.is_file():
        name = file.name or path or "файл"
        raise NotRetriable(f"исходный файл отсутствует: {name}")


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


def legalize_post_schedule(session: object, job: object) -> None:
    """Move a retried post off a slot that the planner would refuse."""
    from datetime import datetime, timezone

    from app.db.models import Account
    from app.services.scheduling import first_legal_slot, placement_problem

    account_id = getattr(job, "account_id", None)
    account = session.get(Account, account_id) if account_id is not None else None  # type: ignore[attr-defined]
    if account is None:
        return
    due = datetime.now(timezone.utc)
    when = getattr(job, "scheduled_for", None) or due
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    start = when if when > due else due
    if placement_problem(session, account, start, ignore_job_id=getattr(job, "id", None)):  # type: ignore[arg-type]
        start = first_legal_slot(session, account, start, ignore_job_id=getattr(job, "id", None))  # type: ignore[arg-type]
    job.scheduled_for = start  # type: ignore[attr-defined]
