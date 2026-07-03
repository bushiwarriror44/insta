"""Event log endpoints."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_db
from app.api.schemas import EventOut
from app.db import Account, Event, EventLevel

router = APIRouter(prefix="/api/events", tags=["events"], dependencies=[AuthDep])


def _serialize(event: Event, *, username_by_id: dict[int, str]) -> EventOut:
    return EventOut(
        id=event.id,
        account_id=event.account_id,
        account_username=username_by_id.get(event.account_id) if event.account_id else None,
        level=event.level.value,
        kind=event.kind,
        message=event.message,
        created_at=event.created_at,
    )


@router.get("", response_model=List[EventOut])
def list_events(
    level: Optional[str] = Query(default=None),
    kind: Optional[str] = Query(default=None),
    username: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[EventOut]:
    stmt = select(Event).order_by(Event.created_at.desc()).limit(limit)
    if level:
        try:
            stmt = stmt.where(Event.level == EventLevel(level))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if kind:
        stmt = stmt.where(Event.kind == kind)
    if username:
        account = db.scalar(select(Account).where(Account.username == username))
        if account is None:
            return []
        stmt = stmt.where(Event.account_id == account.id)

    rows = db.scalars(stmt).all()
    account_ids = {r.account_id for r in rows if r.account_id}
    username_by_id: dict[int, str] = {}
    if account_ids:
        for a in db.scalars(select(Account).where(Account.id.in_(account_ids))).all():
            username_by_id[a.id] = a.username
    return [_serialize(e, username_by_id=username_by_id) for e in rows]
