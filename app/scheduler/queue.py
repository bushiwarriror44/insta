"""Shared claim/retry policy for plan, generation and composition queues."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Event, EventLevel, PipelineStatus
from app.scheduler.backoff import delay_for


class Queued(Protocol):
    id: int
    status: PipelineStatus
    attempts: int
    scheduled_at: datetime
    started_at: datetime | None
    last_error: str | None


JobT = TypeVar("JobT", bound=Queued)


def claim_due(
    session: Session,
    model: type[JobT],
    *,
    now: datetime | None = None,
) -> JobT | None:
    now = now or datetime.now(timezone.utc)
    job = (
        session.execute(
            select(model)
            .where(model.status == PipelineStatus.queued, model.scheduled_at <= now)
            .order_by(model.scheduled_at)
        )
        .scalars()
        .first()
    )
    if job is None:
        return None
    job.status = PipelineStatus.running
    job.started_at = now
    session.add(job)
    session.commit()
    return job


def retry_or_die(
    job: Queued,
    *,
    retryable: bool,
    max_attempts: int,
    now: datetime | None = None,
) -> PipelineStatus:
    now = now or datetime.now(timezone.utc)
    if retryable and job.attempts < max_attempts:
        job.status = PipelineStatus.queued
        job.scheduled_at = now + delay_for(job.attempts)
    else:
        job.status = PipelineStatus.dead
    job.started_at = None
    return job.status


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def reclaim_stale_running(
    session: Session,
    model: type,
    *,
    running: object,
    queued: object,
    older_than: datetime,
    now: datetime | None = None,
) -> int:
    """Return jobs left ``running`` after a dead worker to the queue.

    A render that is still inside its timeout stays ``running``. Only a start
    time older than ``older_than`` (or a missing start time) is treated as a
    crash.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = _as_utc(older_than)
    rows = list(session.scalars(select(model).where(model.status == running)))
    restored = 0
    for job in rows:
        started = getattr(job, "started_at", None)
        if started is not None and _as_utc(started) >= cutoff:
            continue
        job.status = queued
        job.started_at = None
        if hasattr(job, "scheduled_at"):
            job.scheduled_at = now
        if hasattr(job, "scheduled_for"):
            job.scheduled_for = now
        if hasattr(job, "last_error"):
            job.last_error = "воркер прервался, задача возвращена в очередь"
        session.add(job)
        restored += 1
    if restored:
        session.commit()
    return restored


def fail(
    session: Session,
    job: Queued,
    message: str,
    *,
    kind: str,
    retryable: bool,
    max_attempts: int,
    account_id: int | None = None,
    channel_id: int | None = None,
    now: datetime | None = None,
) -> PipelineStatus:
    job.last_error = message
    status = retry_or_die(job, retryable=retryable, max_attempts=max_attempts, now=now)
    account_id = account_id if account_id is not None else channel_id
    session.add(job)
    session.add(
        Event(
            account_id=account_id,
            level=EventLevel.error if status is PipelineStatus.dead else EventLevel.warn,
            kind=kind,
            message=message,
        )
    )
    session.commit()
    return status
