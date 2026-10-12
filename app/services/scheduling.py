"""Queue PostJobs from generated/composed assets onto an account's slots."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Account, GenerationJob, MediaAsset, Platform, PlanJob, PostJob, PostJobStatus, PostType
from app.risk.profiles import profile_cap_for_account, profile_min_gap_for_account
from app.scheduler.planner import CROSS_ACCOUNT_SPREAD_MINUTES, plan_slots_for_day
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


def _scheduled_on_local_day(
    session: Session,
    account: Account,
    when: datetime,
    *,
    ignore_job_id: int | None = None,
) -> int:
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    try:
        tz = ZoneInfo(account.timezone or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    local = when.astimezone(tz)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    filters = [
        PostJob.account_id == account.id,
        PostJob.status.in_(
            [
                PostJobStatus.queued,
                PostJobStatus.running,
                PostJobStatus.done,
                PostJobStatus.awaiting_review,
            ]
        ),
        PostJob.scheduled_for >= start.astimezone(timezone.utc),
        PostJob.scheduled_for < end.astimezone(timezone.utc),
    ]
    if ignore_job_id is not None:
        filters.append(PostJob.id != ignore_job_id)
    count = session.scalar(select(func.count()).select_from(PostJob).where(*filters))
    return int(count or 0)


def _next_active_slot(account: Account, when: datetime) -> datetime:
    """Push a fallback time into the account's active hours."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    try:
        tz = ZoneInfo(account.timezone or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    local = when.astimezone(tz)
    start_h = max(0, min(23, int(account.active_hour_start)))
    end_h = max(start_h + 1, min(24, int(account.active_hour_end)))
    if start_h <= local.hour < end_h:
        return when
    if local.hour < start_h:
        target = local.replace(hour=start_h, minute=0, second=0, microsecond=0)
    else:
        target = (local + timedelta(days=1)).replace(
            hour=start_h, minute=0, second=0, microsecond=0
        )
    return target.astimezone(timezone.utc)


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
    cap = profile_cap_for_account(channel)
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
            when = slot
            if _other_account_close(session, channel.id, when):
                when = when + timedelta(minutes=CROSS_ACCOUNT_SPREAD_MINUTES, seconds=30)
            if when <= now:
                continue
            if _scheduled_on_local_day(session, channel, when) >= cap:
                continue
            if _slot_taken(session, channel.id, when, min_gap):
                continue
            if _other_account_close(session, channel.id, when):
                continue
            asset = remaining.pop(0)
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
            session.flush()

    cursor = _next_active_slot(channel, now + timedelta(minutes=5))
    for asset in remaining:
        hops = 0
        while hops < 40 and (
            _slot_taken(session, channel.id, cursor, min_gap)
            or _scheduled_on_local_day(session, channel, cursor) >= cap
            or _other_account_close(session, channel.id, cursor)
        ):
            if _scheduled_on_local_day(session, channel, cursor) >= cap:
                cursor = _next_active_slot(channel, cursor + timedelta(days=1))
            elif _other_account_close(session, channel.id, cursor):
                cursor = _next_active_slot(
                    channel,
                    cursor + timedelta(minutes=CROSS_ACCOUNT_SPREAD_MINUTES, seconds=30),
                )
            else:
                cursor = _next_active_slot(channel, cursor + timedelta(hours=min_gap))
            hops += 1
        jobs.append(
            _job_for_asset(
                session,
                channel,
                asset,
                when=cursor,
                title=(titles or {}).get(asset.id, asset.label or asset.filename),
                description=description,
                tags=tag_str,
                post_type=ptype,
            )
        )
        session.flush()
        cursor = _next_active_slot(channel, cursor + timedelta(hours=min_gap))
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


def _other_account_close(session: Session, account_id: int, when: datetime) -> bool:
    """True when another account already occupies the cross-account spread."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    delta = timedelta(minutes=CROSS_ACCOUNT_SPREAD_MINUTES)
    return (
        session.scalar(
            select(PostJob.id).where(
                PostJob.account_id != account_id,
                PostJob.status.in_(
                    [
                        PostJobStatus.queued,
                        PostJobStatus.running,
                        PostJobStatus.awaiting_review,
                    ]
                ),
                PostJob.scheduled_for >= when - delta,
                PostJob.scheduled_for <= when + delta,
            )
        )
        is not None
    )


def first_legal_slot(
    session: Session,
    account: Account,
    when: datetime,
    *,
    ignore_job_id: int | None = None,
) -> datetime:
    """Earliest active-hour instant at or after ``when`` that can hold a post."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    cap = profile_cap_for_account(account)
    min_gap = profile_min_gap_for_account(account)
    cursor = _next_active_slot(account, when)
    for _ in range(40):
        day_full = _scheduled_on_local_day(
            session, account, cursor, ignore_job_id=ignore_job_id
        ) >= cap
        if (
            not day_full
            and not _slot_taken(
                session, account.id, cursor, min_gap, ignore_job_id=ignore_job_id
            )
            and not _other_account_close(session, account.id, cursor)
        ):
            return cursor
        if day_full:
            cursor = _next_active_slot(account, cursor + timedelta(days=1))
        elif _other_account_close(session, account.id, cursor):
            cursor = _next_active_slot(
                account,
                cursor + timedelta(minutes=CROSS_ACCOUNT_SPREAD_MINUTES, seconds=30),
            )
        else:
            cursor = _next_active_slot(account, cursor + timedelta(hours=min_gap))
    return cursor


def _slot_taken(
    session: Session,
    account_id: int,
    when: datetime,
    min_gap_hours: float,
    *,
    ignore_job_id: int | None = None,
) -> bool:
    delta = timedelta(hours=min_gap_hours)
    filters = [
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
    ]
    if ignore_job_id is not None:
        filters.append(PostJob.id != ignore_job_id)
    return session.scalar(select(PostJob).where(*filters)) is not None


def placement_problem(
    session: Session,
    account: Account,
    when: datetime,
    *,
    ignore_job_id: int | None = None,
) -> str | None:
    """Why this instant cannot hold a post, or None if it can."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    try:
        tz = ZoneInfo(account.timezone or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    local = when.astimezone(tz)
    start_h = max(0, min(23, int(account.active_hour_start)))
    end_h = max(start_h + 1, min(24, int(account.active_hour_end)))
    cap = profile_cap_for_account(account)
    if not (start_h <= local.hour < end_h):
        reason = "вне часов активности"
    elif _scheduled_on_local_day(session, account, when, ignore_job_id=ignore_job_id) >= cap:
        reason = "на этот день уже набран лимит публикаций"
    elif _slot_taken(
        session,
        account.id,
        when,
        profile_min_gap_for_account(account),
        ignore_job_id=ignore_job_id,
    ):
        reason = "слишком близко к другой публикации этого аккаунта"
    elif _other_account_close(session, account.id, when):
        reason = "слишком близко к публикации другого аккаунта"
    else:
        reason = None
    return reason
