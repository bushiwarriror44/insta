"""The worker saying it is still there, and the reading of that."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import WorkerBeat

DEFAULT_NAME = "worker"
LATE_PERIODS = 3
FLOOR = timedelta(seconds=60)


@dataclass(slots=True)
class WorkerStatus:
    name: str
    seen_at: datetime | None
    stale: bool
    note: str = ""

    @property
    def known(self) -> bool:
        return self.seen_at is not None


def beat(
    session: Session,
    *,
    name: str = DEFAULT_NAME,
    period_seconds: float = 20.0,
    note: str = "",
    now: datetime | None = None,
) -> WorkerBeat:
    now = now or datetime.now(timezone.utc)
    row = session.execute(select(WorkerBeat).where(WorkerBeat.name == name)).scalar_one_or_none()
    if row is None:
        row = WorkerBeat(name=name, started_at=now)
        session.add(row)
    row.seen_at = now
    row.period_seconds = period_seconds
    row.pid = os.getpid()
    row.note = (note or "")[:200]
    session.commit()
    return row


def worker_status(
    session: Session,
    *,
    name: str = DEFAULT_NAME,
    now: datetime | None = None,
) -> WorkerStatus:
    now = now or datetime.now(timezone.utc)
    row = session.execute(select(WorkerBeat).where(WorkerBeat.name == name)).scalar_one_or_none()
    if row is None:
        return WorkerStatus(name=name, seen_at=None, stale=True)
    seen = row.seen_at if row.seen_at.tzinfo else row.seen_at.replace(tzinfo=timezone.utc)
    late_after = max(FLOOR, timedelta(seconds=(row.period_seconds or 20.0) * LATE_PERIODS))
    return WorkerStatus(
        name=name,
        seen_at=seen,
        stale=now - seen > late_after,
        note=row.note or "",
    )
