"""Queue PostJobs from generated/composed assets onto an account's slots."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Account, GenerationJob, MediaAsset, Platform, PlanJob, PostJob, PostJobStatus, PostType
from app.risk.profiles import profile_min_gap_for_account
from app.scheduler.planner import plan_slots_for_day
from app.services.review import initial_job_status


class PlanningError(RuntimeError):
    pass


def post_type_for(account: Account) -> PostType:
    value = getattr(account, "platform", None)
    raw = value.value if hasattr(value, "value") else (value or Platform.instagram.value)
    if raw == Platform.youtube.value:
        return PostType.youtube_short
    if raw == Platform.tiktok.value:
        return PostType.tiktok
    return PostType.reel


def days_ahead_for_plan(
    session: Session,
    *,
    plan_job_id: int | None = None,
    post_group: str | None = None,
) -> int:
    plan_id = plan_job_id
    if plan_id is None and post_group:
        gen = session.scalar(
            select(GenerationJob).where(GenerationJob.post_group == post_group).limit(1)
        )
        if gen is not None:
            plan_id = gen.plan_job_id
    if plan_id is None:
        return 1
    plan = session.get(PlanJob, plan_id)
    days = getattr(plan, "spread_over_days", None) if plan is not None else None
    return max(1, int(days)) if days else 1


def schedule_assets(
    session: Session,
    channel: Account,
    assets: list[MediaAsset],
    *,
    titles: dict[int, str] | None = None,
    description: str = "",
    tags: list[str] | None = None,
    days_ahead: int = 1,
) -> list[PostJob]:
    if not assets:
        raise PlanningError("нет клипов для постановки")
    now = datetime.now(timezone.utc)
    days = max(1, int(days_ahead or 1))
    remaining = list(assets)
    tag_str = ",".join(tags or [])
    ptype = post_type_for(channel)
    min_gap = profile_min_gap_for_account(channel)
    jobs: list[PostJob] = []

    for day_offset in range(days):
        if not remaining:
            break
        day = now + timedelta(days=day_offset)
        slots = plan_slots_for_day(channel, day, count=len(remaining))
        for slot in slots:
            if not remaining:
                break
            if slot <= now:
                continue
            if _slot_taken(session, channel.id, slot, min_gap):
                continue
            asset = remaining.pop(0)
            jobs.append(
                _job_for_asset(
                    session,
                    channel,
                    asset,
                    when=slot,
                    title=(titles or {}).get(asset.id, asset.label or asset.filename),
                    description=description,
                    tags=tag_str,
                    post_type=ptype,
                )
            )
            session.flush()

    for i, asset in enumerate(remaining):
        when = now + timedelta(minutes=5 * (len(jobs) + i + 1))
        jobs.append(
            _job_for_asset(
                session,
                channel,
                asset,
                when=when,
                title=(titles or {}).get(asset.id, asset.label or asset.filename),
                description=description,
                tags=tag_str,
                post_type=ptype,
            )
        )
    session.commit()
    return jobs


def _job_for_asset(
    session: Session,
    channel: Account,
    asset: MediaAsset,
    *,
    when: datetime,
    title: str,
    description: str,
    tags: str,
    post_type: PostType,
) -> PostJob:
    path = (settings.media_dir / asset.filename).resolve()
    if not path.exists():
        raise PlanningError(f"файл не найден: {asset.filename}")
    job = PostJob(
        account_id=channel.id,
        source_video_path=str(path),
        post_type=post_type,
        title=title,
        description=description,
        tags=tags,
        caption_template=title,
        scheduled_for=when,
        status=initial_job_status(channel),
    )
    session.add(job)
    return job


def _slot_taken(session: Session, account_id: int, when: datetime, min_gap_hours: float) -> bool:
    delta = timedelta(hours=min_gap_hours)
    return (
        session.scalar(
            select(PostJob).where(
                PostJob.account_id == account_id,
                PostJob.status.in_(
                    [
                        PostJobStatus.queued,
                        PostJobStatus.running,
                        PostJobStatus.done,
                        PostJobStatus.awaiting_review,
                    ]
                ),
                PostJob.scheduled_for >= when - delta,
                PostJob.scheduled_for <= when + delta,
            )
        )
        is not None
    )
