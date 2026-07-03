"""Tests for app.scheduler.planner."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from app.db import DailyStat, PostJob, PostJobStatus
from app.scheduler import planner as planner_module
from app.scheduler.planner import (
    can_post_today,
    increment_daily_stat,
    plan_slots_for_day,
    schedule_jobs,
)


@pytest.fixture(autouse=True)
def _disable_offday(monkeypatch):
    """Existing planner tests assume slots are produced — disable the
    probabilistic off-day skip for the legacy assertions. Tests for the
    new behaviour set the probability explicitly."""
    monkeypatch.setattr(planner_module, "DAILY_SKIP_PROB", 0.0, raising=True)


def test_plan_slots_for_day_respects_window_and_cap(make_account):
    account = make_account(active_hour_start=10, active_hour_end=22, daily_post_cap=3, min_gap_hours=4.0)
    target = datetime.now(timezone.utc) + timedelta(days=1)
    rng = random.Random(42)
    slots = plan_slots_for_day(account, target, rng=rng)

    assert 1 <= len(slots) <= 3
    # All slots inside [10:00, 22:00] local (UTC here)
    for s in slots:
        local = s.astimezone(timezone.utc)
        assert 10 <= local.hour <= 22

    # min gap respected
    sorted_slots = sorted(slots)
    for a, b in zip(sorted_slots, sorted_slots[1:]):
        assert (b - a).total_seconds() >= 4 * 3600 - 60


def test_plan_slots_invalid_window(make_account):
    account = make_account(active_hour_start=22, active_hour_end=20)
    slots = plan_slots_for_day(account, datetime.now(timezone.utc))
    assert slots == []


def test_plan_slots_count_clamped_by_cap(make_account):
    account = make_account(daily_post_cap=2, min_gap_hours=1.0, active_hour_start=10, active_hour_end=22)
    slots = plan_slots_for_day(account, datetime.now(timezone.utc), count=999)
    assert len(slots) <= 2


def test_schedule_jobs_creates_records_round_robin(db_session, make_account):
    account = make_account(daily_post_cap=2, min_gap_hours=4.0)
    sources = ["/v/a.mp4", "/v/b.mp4", "/v/c.mp4"]
    created = schedule_jobs(db_session, account, sources, days_ahead=1, rng=random.Random(7))

    assert len(created) <= 2
    times = [job.scheduled_for for job in created]
    assert times == sorted(times)
    sources_used = [job.source_video_path for job in created]
    for src in sources_used:
        assert src in sources


def test_schedule_jobs_no_sources(db_session, make_account):
    account = make_account()
    assert schedule_jobs(db_session, account, []) == []


def test_too_close_to_existing_filters(db_session, make_account):
    account = make_account(daily_post_cap=10, min_gap_hours=4.0, active_hour_start=10, active_hour_end=22)
    existing_when = datetime.now(timezone.utc) + timedelta(days=1, hours=12)
    db_session.add(
        PostJob(
            account_id=account.id,
            source_video_path="/v.mp4",
            scheduled_for=existing_when,
            status=PostJobStatus.queued,
        )
    )
    db_session.commit()

    rng = random.Random(0)
    created = schedule_jobs(db_session, account, ["/x.mp4"], days_ahead=2, rng=rng)
    for job in created:
        assert abs((job.scheduled_for - existing_when).total_seconds()) >= 4 * 3600


def test_can_post_today_under_cap(db_session, make_account):
    account = make_account(daily_post_cap=2, timezone="UTC")
    assert can_post_today(db_session, account)


def test_can_post_today_at_cap(db_session, make_account):
    account = make_account(daily_post_cap=1, timezone="UTC")
    today = datetime.now(timezone.utc).date().isoformat()
    db_session.add(DailyStat(account_id=account.id, date_key=today, posts_count=1))
    db_session.commit()
    assert can_post_today(db_session, account) is False


def test_increment_daily_stat_creates_and_updates(db_session, make_account):
    account = make_account()
    increment_daily_stat(db_session, account, success=True)
    increment_daily_stat(db_session, account, success=True)
    increment_daily_stat(db_session, account, success=False)

    today = datetime.now(timezone.utc).date().isoformat()
    stat = db_session.query(DailyStat).filter_by(account_id=account.id, date_key=today).one()
    assert stat.posts_count == 2
    assert stat.failures_count == 1


def test_account_with_named_timezone_works(make_account):
    account = make_account(timezone="Europe/Berlin", active_hour_start=10, active_hour_end=22)
    rng = random.Random(0)
    slots = plan_slots_for_day(account, datetime.now(timezone.utc) + timedelta(days=1), rng=rng)
    # Slots are returned in UTC; validate they correspond to a correct local window.
    from zoneinfo import ZoneInfo

    for s in slots:
        local = s.astimezone(ZoneInfo("Europe/Berlin"))
        assert 10 <= local.hour <= 22


def test_account_with_invalid_timezone_falls_back(make_account):
    account = make_account(timezone="Not/AZone", active_hour_start=10, active_hour_end=22)
    slots = plan_slots_for_day(account, datetime.now(timezone.utc) + timedelta(days=1))
    assert isinstance(slots, list)


# ---------------------------------------------------------------------------
# New anti-detection behaviour: off-days, prime-time weighting, cross-account.
# ---------------------------------------------------------------------------


def test_off_day_returns_empty(make_account, monkeypatch):
    """When the daily-skip dice rolls under DAILY_SKIP_PROB the planner must
    return zero slots, even with daily_post_cap>0."""
    monkeypatch.setattr(planner_module, "DAILY_SKIP_PROB", 1.0, raising=True)
    account = make_account()
    slots = plan_slots_for_day(account, datetime.now(timezone.utc) + timedelta(days=1))
    assert slots == []


def test_prime_time_distribution_is_biased_toward_evening(make_account, monkeypatch):
    """Sample many slots and confirm the histogram peaks at the configured
    weekday prime-time hours rather than being uniform."""
    monkeypatch.setattr(planner_module, "DAILY_SKIP_PROB", 0.0, raising=True)
    account = make_account(active_hour_start=10, active_hour_end=22, daily_post_cap=1)
    rng = random.Random(123)
    # Force a known weekday baseline: the 1st of January 2024 was a Monday.
    target = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    bucket: dict[int, int] = {}
    for _ in range(400):
        slots = plan_slots_for_day(account, target, count=1, rng=rng)
        if slots:
            bucket[slots[0].astimezone(timezone.utc).hour] = bucket.get(slots[0].astimezone(timezone.utc).hour, 0) + 1
    # Evening hours (19-21) collectively must beat early-morning hours (10-12).
    evening = sum(bucket.get(h, 0) for h in (19, 20, 21))
    early = sum(bucket.get(h, 0) for h in (10, 11, 12))
    assert evening > early


def test_cross_account_spread_avoids_simultaneous_posts(db_session, make_account):
    """A second account must not be scheduled within ±2 minutes of an
    existing job, even if its own min_gap window is otherwise empty."""
    proxy_account = make_account(username="acc-a", min_gap_hours=1.0, daily_post_cap=5)
    other = make_account(username="acc-b", min_gap_hours=1.0, daily_post_cap=5)

    # Plant a queued job for account A right inside everyone's active window.
    when = (datetime.now(timezone.utc) + timedelta(days=1)).replace(
        hour=15, minute=0, second=0, microsecond=0
    )
    db_session.add(
        PostJob(
            account_id=proxy_account.id,
            source_video_path="/v/a.mp4",
            scheduled_for=when,
            status=PostJobStatus.queued,
        )
    )
    db_session.commit()

    rng = random.Random(0)
    created = schedule_jobs(db_session, other, ["/v/b.mp4"], days_ahead=2, rng=rng)
    for job in created:
        delta = abs((job.scheduled_for - when).total_seconds())
        assert delta >= planner_module.CROSS_ACCOUNT_SPREAD_MINUTES * 60
