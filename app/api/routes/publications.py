"""Publication history and statistics endpoints."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_db
from app.api.schemas import PublicationOut
from app.db import Account, PostLog
from app.publications.stats import refresh_post_log_stats

router = APIRouter(prefix="/api/publications", tags=["publications"], dependencies=[AuthDep])


def _serialize(row: PostLog, *, db: Session) -> PublicationOut:
    account = db.get(Account, row.account_id)
    return PublicationOut(
        id=row.id,
        job_id=row.job_id,
        account_id=row.account_id,
        account_username=account.username if account else None,
        post_type=row.post_type,
        media_id=row.media_id,
        media_code=row.media_code,
        final_media_path=row.final_video_path,
        final_caption=row.final_caption,
        success=row.success,
        error=row.error,
        view_count=row.view_count,
        like_count=row.like_count,
        comment_count=row.comment_count,
        play_count=row.play_count,
        save_count=row.save_count,
        share_count=row.share_count,
        last_stats_at=row.last_stats_at,
        created_at=row.created_at,
    )


@router.get("", response_model=List[PublicationOut])
def list_publications(
    username: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[PublicationOut]:
    stmt = select(PostLog).order_by(PostLog.created_at.desc()).limit(limit)
    if username:
        account = db.scalar(select(Account).where(Account.username == username))
        if account is None:
            return []
        stmt = stmt.where(PostLog.account_id == account.id)
    rows = db.scalars(stmt).all()
    return [_serialize(row, db=db) for row in rows]


@router.post("/{publication_id}/refresh-stats", response_model=PublicationOut)
def refresh_publication_stats(
    publication_id: int,
    db: Session = Depends(get_db),
) -> PublicationOut:
    row = db.get(PostLog, publication_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Публикация не найдена")
    try:
        row = refresh_post_log_stats(db, row)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Не удалось обновить статистику: {exc}",
        ) from exc
    return _serialize(row, db=db)
