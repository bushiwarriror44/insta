"""Human-like posting schedule planner.

Picks publication slots inside the account's local active hours, respects
``min_gap_hours`` between posts and the daily cap. The output is a list of
timezone-aware UTC datetimes ready to drop into ``post_jobs.scheduled_for``.

Anti-detection extensions
-------------------------

* Prime-time weighting: instead of a uniform random offset across the active
  window, slots are sampled from a *weighted* hour distribution that peaks at
  realistic engagement times (lunch + early evening on weekdays, midday +
  evening on weekends). A bot that posts uniformly at every hour-of-day is a
  textbook automation tell; weighting biases the distribution toward times
  organic creators actually post.
* Off-day probability: with a small chance per day, the planner returns no
  slots at all. Real users skip days. A perfectly daily upload streak across
  30+ accounts is one of the cheapest pattern-matching signals available to
  Instagram.
* Cross-account spread: when scheduling a new job, we also look at *other*
  accounts on the same proxy provider (heuristically: any account) and avoid
  scheduling within ±2 minutes of an existing slot. Helps keep multiple
  accounts on the same residential range from posting in lockstep.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Iterable, List
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Account, PostJob, PostJobStatus
from app.logging_setup import get_logger
from app.risk.profiles import classify_account_risk, profile_cap_for_account, profile_min_gap_for_account
from app.services.review import initial_job_status

logger = get_logger(__name__)


# Per-hour weights (index = local hour 0..23). Hand-tuned to mirror typical
# Instagram engagement curves — peaks at lunch and prime-time evening.
WEEKDAY_HOUR_WEIGHTS: list[float] = [
    0.05, 0.05, 0.04, 0.03, 0.03, 0.04, 0.06, 0.10,  # 00–07
    0.20, 0.35, 0.55, 0.80, 0.90, 0.95, 0.70, 0.55,  # 08–15
    0.50, 0.55, 0.75, 1.00, 0.95, 0.90, 0.55, 0.20,  # 16–23
]

WEEKEND_HOUR_WEIGHTS: list[float] = [
    0.06, 0.06, 0.05, 0.04, 0.03, 0.03, 0.04, 0.05,  # 00–07
    0.10, 0.20, 0.45, 0.70, 0.85, 0.85, 0.70, 0.55,  # 08–15
    0.50, 0.55, 0.65, 0.80, 0.95, 1.00, 0.65, 0.30,  # 16–23
]


# Probability that a given (account, day) combo is *skipped* entirely.
DAILY_SKIP_PROB = 0.08


def _account_tz(account: Account) -> ZoneInfo:
    try:
        return ZoneInfo(account.timezone)
    except Exception:
        return ZoneInfo("UTC")


def _weights_for_day(target_local: datetime) -> list[float]:
    return WEEKEND_HOUR_WEIGHTS if target_local.weekday() >= 5 else WEEKDAY_HOUR_WEIGHTS


def _weighted_offset_pick(
    rng: random.Random,
    start_h: int,
    end_h: int,
    weights: list[float],
) -> int:
    """Return a minute-offset in ``[0, (end_h - start_h)*60)`` weighted by
    per-hour engagement scores.
    """
    span_hours = max(1, end_h - start_h)
    bucket_weights = [max(weights[(start_h + i) % 24], 0.001) for i in range(span_hours)]
    bucket = rng.choices(range(span_hours), weights=bucket_weights, k=1)[0]
    minute = rng.randint(0, 59)
    return bucket * 60 + minute


def plan_slots_for_day(
    account: Account,
    target_day: datetime,
    count: int | None = None,
    rng: random.Random | None = None,
) -> List[datetime]:
    """Return up to ``count`` UTC datetimes within ``target_day``'s active hours.

    Slots respect:
      - ``account.active_hour_start`` / ``active_hour_end`` (in the account's TZ)
      - ``account.min_gap_hours`` between consecutive slots
      - ``account.daily_post_cap`` as the upper bound on count
      - Probabilistic off-day skip (``DAILY_SKIP_PROB``)
      - Per-hour engagement weighting
    """
    rng = rng or random.Random()
    tz = _account_tz(account)
    cap_limit = profile_cap_for_account(account)
    cap = min(count or cap_limit, cap_limit)
    if cap <= 0:
        return []

    # Off-day: with low probability, return zero slots even if cap > 0.
    profile = classify_account_risk(account)
    if rng.random() < (DAILY_SKIP_PROB * profile.off_day_prob_multiplier):
        logger.info("planner.off_day", username=account.username, day=target_day.astimezone(tz).date().isoformat())
        return []

    start_local = target_day.astimezone(tz).replace(
        hour=account.active_hour_start, minute=0, second=0, microsecond=0
    )
    end_h = min(account.active_hour_end, 23)
    end_local = start_local.replace(hour=end_h)
    if end_local <= start_local:
        return []

    window_minutes = int((end_local - start_local).total_seconds() // 60)
    min_gap_minutes = max(1, int(profile_min_gap_for_account(account) * 60))

    if window_minutes < min_gap_minutes * (cap - 1):
        cap = max(1, window_minutes // min_gap_minutes + 1)

    weights = _weights_for_day(start_local)

    chosen: List[datetime] = []
    attempts = 0
    while len(chosen) < cap and attempts < 200:
        attempts += 1
        offset = _weighted_offset_pick(rng, account.active_hour_start, end_h, weights)
        offset += rng.randint(-7, 7)
        offset = max(0, min(window_minutes - 1, offset))
        candidate_local = start_local + timedelta(minutes=offset)
        if all(
            abs((candidate_local - existing).total_seconds()) >= min_gap_minutes * 60
            for existing in chosen
        ):
            chosen.append(candidate_local)

    chosen.sort()
    return [dt.astimezone(timezone.utc) for dt in chosen]


# Cross-account spread: minimum spacing (minutes) between two queued jobs
# from any account in the system. Prevents lockstep posting across accounts.
CROSS_ACCOUNT_SPREAD_MINUTES = 2


def schedule_jobs(
    db: Session,
    account: Account,
    sources: Iterable[str],
    caption_template: str | None = None,
    days_ahead: int = 1,
    rng: random.Random | None = None,
) -> list[PostJob]:
    """Create ``PostJob`` rows for the given video sources across N days.

    Sources are consumed round-robin per slot.
    """
    rng = rng or random.Random()
    sources_list = list(sources)
    if not sources_list:
        return []

    now_utc = datetime.now(timezone.utc)
    created: list[PostJob] = []
    src_idx = 0

    for day_offset in range(days_ahead):
        day = now_utc + timedelta(days=day_offset)
        slots = plan_slots_for_day(account, day, rng=rng)
        for slot in slots:
            if slot <= now_utc:
                continue
            if _too_close_to_existing(db, account.id, slot, profile_min_gap_for_account(account)):
                continue
            if _too_close_to_others_in_pool(db, slot):
                continue
            video_path = sources_list[src_idx % len(sources_list)]
            src_idx += 1
            job = PostJob(
                account_id=account.id,
                source_video_path=video_path,
                caption_template=caption_template,
                scheduled_for=slot,
                status=initial_job_status(account),
            )
            db.add(job)
            created.append(job)

    if created:
        db.commit()
        logger.info(
            "planner.scheduled",
            username=account.username,
            count=len(created),
            first=created[0].scheduled_for.isoformat(),
            last=created[-1].scheduled_for.isoformat(),
        )
    return created


def _too_close_to_existing(db: Session, account_id: int, when: datetime, min_gap_hours: float) -> bool:
    delta = timedelta(hours=min_gap_hours)
    stmt = select(PostJob).where(
        PostJob.account_id == account_id,
        PostJob.status.in_([PostJobStatus.queued, PostJobStatus.running, PostJobStatus.done]),
        PostJob.scheduled_for >= when - delta,
        PostJob.scheduled_for <= when + delta,
    )
    return db.scalar(stmt) is not None


def _too_close_to_others_in_pool(db: Session, when: datetime) -> bool:
    """True if any *other* account already has a queued/running job within
    ``CROSS_ACCOUNT_SPREAD_MINUTES`` minutes of ``when``.
    """
    delta = timedelta(minutes=CROSS_ACCOUNT_SPREAD_MINUTES)
    stmt = select(PostJob).where(
        PostJob.status.in_([PostJobStatus.queued, PostJobStatus.running]),
        PostJob.scheduled_for >= when - delta,
        PostJob.scheduled_for <= when + delta,
    )
    return db.scalar(stmt) is not None


def can_post_today(db: Session, account: Account, when: datetime | None = None) -> bool:
    """Check whether the daily cap would be exceeded if we post now."""
    when = when or datetime.now(timezone.utc)
    tz = _account_tz(account)
    local_day = when.astimezone(tz).date().isoformat()

    from app.db import DailyStat  # local import to avoid cycle

    stat = db.scalar(select(DailyStat).where(DailyStat.account_id == account.id, DailyStat.date_key == local_day))
    posted = stat.posts_count if stat else 0
    return posted < profile_cap_for_account(account)


def increment_daily_stat(db: Session, account: Account, when: datetime | None = None, *, success: bool) -> None:
    when = when or datetime.now(timezone.utc)
    tz = _account_tz(account)
    local_day = when.astimezone(tz).date().isoformat()

    from app.db import DailyStat

    stat = db.scalar(select(DailyStat).where(DailyStat.account_id == account.id, DailyStat.date_key == local_day))
    if stat is None:
        stat = DailyStat(account_id=account.id, date_key=local_day, posts_count=0, failures_count=0)
        db.add(stat)
    if success:
        stat.posts_count += 1
    else:
        stat.failures_count += 1
    db.commit()
