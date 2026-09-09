"""Dashboard summary endpoint."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_db
from app.api.schemas import DailyStatRow, DashboardSummary, EventOut
from app.db import Account, AccountStatus, Clarification, DailyStat, Event, PostJob, PostJobStatus, Proxy

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], dependencies=[AuthDep])


@router.get("", response_model=DashboardSummary)
def dashboard(db: Session = Depends(get_db)) -> DashboardSummary:
    accounts_total = db.scalar(select(func.count(Account.id))) or 0
    accounts_active = (
        db.scalar(select(func.count(Account.id)).where(Account.status == AccountStatus.active)) or 0
    )
    accounts_blocked = (
        db.scalar(select(func.count(Account.id)).where(Account.status == AccountStatus.blocked)) or 0
    )

    proxies_total = db.scalar(select(func.count(Proxy.id))) or 0
    proxies_healthy = (
        db.scalar(select(func.count(Proxy.id)).where(Proxy.is_healthy.is_(True))) or 0
    )

    jobs_queued = (
        db.scalar(select(func.count(PostJob.id)).where(PostJob.status == PostJobStatus.queued)) or 0
    )
    jobs_running = (
        db.scalar(select(func.count(PostJob.id)).where(PostJob.status == PostJobStatus.running)) or 0
    )
    jobs_dead_total = (
        db.scalar(select(func.count(PostJob.id)).where(PostJob.status == PostJobStatus.dead)) or 0
    )
    risk_since = datetime.now(timezone.utc) - timedelta(hours=24)
    jobs_awaiting_review = (
        db.scalar(
            select(func.count(PostJob.id)).where(PostJob.status == PostJobStatus.awaiting_review)
        )
        or 0
    )
    jobs_failed_24h = (
        db.scalar(
            select(func.count(PostJob.id)).where(
                PostJob.status.in_([PostJobStatus.failed, PostJobStatus.dead]),
                PostJob.finished_at >= risk_since,
            )
        )
        or 0
    )
    open_questions = (
        db.scalar(
            select(func.count(Clarification.id)).where(
                Clarification.answer.is_(None),
                Clarification.dismissed.is_(False),
            )
        )
        or 0
    )
    risk_signals_24h = (
        db.scalar(
            select(func.count(Event.id)).where(
                Event.created_at >= risk_since,
                Event.kind.in_(["risk.quarantine", "proxy.unstable", "risk.soft_signal"]),
            )
        )
        or 0
    )
    quarantined_accounts = (
        db.scalar(select(func.count(Account.id)).where(Account.status == AccountStatus.cooldown)) or 0
    )

    today = datetime.now(timezone.utc).date().isoformat()
    jobs_done_today_stmt = select(func.coalesce(func.sum(DailyStat.posts_count), 0)).where(
        DailyStat.date_key == today
    )
    jobs_done_today = db.scalar(jobs_done_today_stmt) or 0

    daily_rows: list[DailyStatRow] = []
    stats_today = db.scalars(select(DailyStat).where(DailyStat.date_key == today)).all()
    if stats_today:
        username_by_id = {
            a.id: a.username
            for a in db.scalars(
                select(Account).where(Account.id.in_([s.account_id for s in stats_today]))
            ).all()
        }
        for s in stats_today:
            daily_rows.append(
                DailyStatRow(
                    username=username_by_id.get(s.account_id, f"id:{s.account_id}"),
                    posts_count=s.posts_count,
                    failures_count=s.failures_count,
                )
            )

    recent: list[EventOut] = []
    events = db.scalars(select(Event).order_by(Event.created_at.desc()).limit(10)).all()
    if events:
        ids = {e.account_id for e in events if e.account_id}
        username_by_id: dict[int, str] = {}
        if ids:
            for a in db.scalars(select(Account).where(Account.id.in_(ids))).all():
                username_by_id[a.id] = a.username
        for e in events:
            recent.append(
                EventOut(
                    id=e.id,
                    account_id=e.account_id,
                    account_username=username_by_id.get(e.account_id) if e.account_id else None,
                    level=e.level.value,
                    kind=e.kind,
                    message=e.message,
                    created_at=e.created_at,
                )
            )

    return DashboardSummary(
        accounts_total=accounts_total,
        accounts_active=accounts_active,
        accounts_blocked=accounts_blocked,
        proxies_healthy=proxies_healthy,
        proxies_total=proxies_total,
        jobs_queued=jobs_queued,
        jobs_running=jobs_running,
        jobs_done_today=jobs_done_today,
        jobs_dead_total=jobs_dead_total,
        jobs_awaiting_review=jobs_awaiting_review,
        jobs_failed_24h=jobs_failed_24h,
        open_questions=open_questions,
        risk_signals_24h=risk_signals_24h,
        quarantined_accounts=quarantined_accounts,
        daily_stats=daily_rows,
        recent_events=recent,
    )
