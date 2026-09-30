"""Job listing + manual enqueue endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_db
from app.api.schemas import DiagnosticRunOut, EnqueueIn, JobOut
from app.db import Account, DiagnosticRun, PostJob, PostJobStatus, PostType
from app.api.routes.diagnostics import _to_run_out
from app.api.routes.videos import _resolve_source_file, media_type_for_name
from app.services.review import initial_job_status

router = APIRouter(prefix="/api/jobs", tags=["jobs"], dependencies=[AuthDep])


def _serialize(job: PostJob, *, db: Session) -> JobOut:
    account = db.get(Account, job.account_id)
    return JobOut(
        id=job.id,
        account_id=job.account_id,
        account_username=account.username if account else None,
        source_video_path=job.source_video_path,
        post_type=(job.post_type.value if hasattr(job.post_type, "value") else (job.post_type or "reel")),
        caption_template=job.caption_template,
        title=getattr(job, "title", "") or "",
        description=getattr(job, "description", None) or "",
        tags=getattr(job, "tags", None) or "",
        scheduled_for=job.scheduled_for,
        status=job.status.value,
        attempts=job.attempts,
        last_error=job.last_error,
        next_attempt_at=job.next_attempt_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        created_at=job.created_at,
    )


@router.get("", response_model=List[JobOut])
def list_jobs(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    username: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[JobOut]:
    stmt = select(PostJob).order_by(PostJob.scheduled_for.desc()).limit(limit)
    if status_filter:
        try:
            stmt = stmt.where(PostJob.status == PostJobStatus(status_filter))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if username:
        account = db.scalar(select(Account).where(Account.username == username))
        if account is None:
            return []
        stmt = stmt.where(PostJob.account_id == account.id)
    rows = db.scalars(stmt).all()
    return [_serialize(j, db=db) for j in rows]


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def enqueue_job(payload: EnqueueIn, db: Session = Depends(get_db)) -> JobOut:
    account = db.scalar(select(Account).where(Account.username == payload.username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{payload.username}' not found")

    filename = payload.selected_filename
    try:
        src = _resolve_source_file(filename)
    except HTTPException:
        raise
    try:
        media_type = media_type_for_name(src.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if payload.post_type == "feed_photo" and media_type != "image":
        raise HTTPException(status_code=400, detail="feed_photo requires an image file")
    if payload.post_type in ("reel", "feed_video", "youtube_short", "tiktok") and media_type != "video":
        raise HTTPException(status_code=400, detail=f"{payload.post_type} requires a video file")

    when = payload.when or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)

    job = PostJob(
        account_id=account.id,
        source_video_path=str(src.resolve()),
        post_type=PostType(payload.post_type),
        caption_template=payload.caption_template,
        title=payload.title or "",
        description=payload.description or "",
        tags=payload.tags or "",
        privacy=payload.privacy or "public",
        scheduled_for=when,
        status=initial_job_status(account),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return _serialize(job, db=db)


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: int, db: Session = Depends(get_db)) -> JobOut:
    job = db.get(PostJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in (PostJobStatus.queued, PostJobStatus.failed, PostJobStatus.awaiting_review):
        raise HTTPException(status_code=400, detail=f"Cannot cancel job in status '{job.status.value}'")
    job.status = PostJobStatus.cancelled
    db.commit()
    db.refresh(job)
    return _serialize(job, db=db)


@router.post("/{job_id}/approve", response_model=JobOut)
def approve_job(job_id: int, db: Session = Depends(get_db)) -> JobOut:
    from app.services.review import NotHeld, approve

    job = db.get(PostJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        approve(db, job)
    except NotHeld as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _serialize(job, db=db)


@router.post("/{job_id}/retry", response_model=JobOut)
def retry_job(job_id: int, db: Session = Depends(get_db)) -> JobOut:
    from app.services.retry import NotRetriable, revive

    job = db.get(PostJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        revive(job)
    except NotRetriable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    db.refresh(job)
    return _serialize(job, db=db)


class RescheduleIn(BaseModel):
    when: datetime


@router.patch("/{job_id}", response_model=JobOut)
def reschedule_job(job_id: int, payload: RescheduleIn, db: Session = Depends(get_db)) -> JobOut:
    job = db.get(PostJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in (
        PostJobStatus.queued,
        PostJobStatus.awaiting_review,
        PostJobStatus.failed,
    ):
        raise HTTPException(status_code=409, detail=f"Cannot move job in status '{job.status.value}'")
    when = payload.when
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    job.scheduled_for = when
    db.commit()
    db.refresh(job)
    return _serialize(job, db=db)


@router.get("/{job_id}/logs", response_model=List[DiagnosticRunOut])
def job_diagnostic_logs(job_id: int, db: Session = Depends(get_db)) -> List[DiagnosticRunOut]:
    job = db.get(PostJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    account = db.get(Account, job.account_id)
    runs = db.scalars(
        select(DiagnosticRun)
        .where(DiagnosticRun.job_id == job_id)
        .order_by(DiagnosticRun.created_at.asc())
    ).all()
    username = account.username if account else None
    return [_to_run_out(r, account_username=username) for r in runs]
