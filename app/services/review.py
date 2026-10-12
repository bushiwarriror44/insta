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
    from app.services.retry import NotRetriable, ensure_post_source

    try:
        ensure_post_source(job.source_video_path)
    except NotRetriable as exc:
        raise NotHeld(str(exc)) from exc
    job.status = PostJobStatus.queued
    job.next_attempt_at = None
    due = now or datetime.now(timezone.utc)
    if job.scheduled_for.tzinfo is None:
        when = job.scheduled_for.replace(tzinfo=timezone.utc)
    else:
        when = job.scheduled_for
    start = when if when > due else due
    from app.db.models import Account
    from app.services.scheduling import first_legal_slot, placement_problem

    account = session.get(Account, job.account_id)
    if account is None:
        raise NotHeld("аккаунт публикации не найден")
    if placement_problem(session, account, start, ignore_job_id=job.id):
        start = first_legal_slot(session, account, start, ignore_job_id=job.id)
    job.scheduled_for = start
    session.add(job)
    session.commit()
    session.refresh(job)
    return job
