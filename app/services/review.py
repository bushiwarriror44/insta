"""Holding a post for a person, and letting it go."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import PostJob, PostJobStatus


class NotHeld(RuntimeError):
    """This post is not waiting on anyone."""


def initial_job_status(account: object) -> PostJobStatus:
    """Queue immediately, or hold if the account requires a human look."""
    if bool(getattr(account, "hold_for_review", False)):
        return PostJobStatus.awaiting_review
    return PostJobStatus.queued


def approve(session: Session, job: PostJob, *, now: datetime | None = None) -> PostJob:
    """Release a held post into the worker's queue."""
    if job.status is not PostJobStatus.awaiting_review:
        raise NotHeld(f"публикация в состоянии «{job.status.value}» не ждёт проверки")
    job.status = PostJobStatus.queued
    job.next_attempt_at = None
    due = now or datetime.now(timezone.utc)
    if job.scheduled_for.tzinfo is None:
        when = job.scheduled_for.replace(tzinfo=timezone.utc)
    else:
        when = job.scheduled_for
    if when > due:
        job.scheduled_for = when
    else:
        job.scheduled_for = due
    session.add(job)
    session.commit()
    session.refresh(job)
    return job
