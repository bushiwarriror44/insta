"""Post review / hold_for_review."""
from datetime import datetime, timedelta, timezone

from app.db.models import PostJob, PostJobStatus
from app.services.review import NotHeld, approve, initial_job_status


def test_initial_job_status_hold_for_review(make_account):
    account = make_account(hold_for_review=True)
    assert initial_job_status(account) is PostJobStatus.awaiting_review


def test_initial_job_status_default_queued(make_account):
    account = make_account()
    assert initial_job_status(account) is PostJobStatus.queued


def test_approve_moves_past_scheduled_for_to_now(db_session, make_account, tmp_path):
    account = make_account()
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    video = tmp_path / "x.mp4"
    video.write_bytes(b"x")
    job = PostJob(
        account_id=account.id,
        source_video_path=str(video),
        status=PostJobStatus.awaiting_review,
        scheduled_for=past,
    )
    db_session.add(job)
    db_session.commit()
    now = datetime.now(timezone.utc)
    approve(db_session, job, now=now)
    db_session.refresh(job)
    assert job.status is PostJobStatus.queued
    scheduled = job.scheduled_for
    if scheduled.tzinfo is None:
        scheduled = scheduled.replace(tzinfo=timezone.utc)
    assert scheduled >= now


def test_approve_keeps_future_scheduled_for(db_session, make_account, tmp_path):
    account = make_account()
    future = (datetime.now(timezone.utc) + timedelta(days=1)).replace(
        hour=16, minute=0, second=0, microsecond=0
    )
    video = tmp_path / "x.mp4"
    video.write_bytes(b"x")
    job = PostJob(
        account_id=account.id,
        source_video_path=str(video),
        status=PostJobStatus.awaiting_review,
        scheduled_for=future,
    )
    db_session.add(job)
    db_session.commit()
    approve(db_session, job, now=datetime.now(timezone.utc))
    db_session.refresh(job)
    stored = job.scheduled_for
    if stored.tzinfo is None:
        stored = stored.replace(tzinfo=timezone.utc)
    assert abs((stored - future).total_seconds()) < 1


def test_approve_moves_off_full_day_and_night(db_session, make_account, tmp_path):
    video = tmp_path / "held.mp4"
    video.write_bytes(b"x")
    account = make_account(
        username="approve-cap",
        daily_post_cap=1,
        min_gap_hours=1.0,
        timezone="UTC",
        active_hour_start=10,
        active_hour_end=22,
    )
    day = datetime(2026, 10, 12, 18, 0, tzinfo=timezone.utc)
    db_session.add(
        PostJob(
            account_id=account.id,
            source_video_path=str(video),
            status=PostJobStatus.done,
            scheduled_for=day.replace(hour=10),
        )
    )
    held = PostJob(
        account_id=account.id,
        source_video_path=str(video),
        status=PostJobStatus.awaiting_review,
        scheduled_for=day,
    )
    db_session.add(held)
    db_session.commit()
    approve(db_session, held, now=datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc))
    db_session.refresh(held)
    landed = held.scheduled_for
    if landed.tzinfo is None:
        landed = landed.replace(tzinfo=timezone.utc)
    assert landed.date().isoformat() != "2026-10-12"
    assert 10 <= landed.hour < 22

    night_account = make_account(
        username="approve-night",
        timezone="UTC",
        active_hour_start=10,
        active_hour_end=22,
    )
    night = PostJob(
        account_id=night_account.id,
        source_video_path=str(video),
        status=PostJobStatus.awaiting_review,
        scheduled_for=datetime(2026, 10, 13, 23, 15, tzinfo=timezone.utc),
    )
    db_session.add(night)
    db_session.commit()
    approve(db_session, night, now=datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc))
    db_session.refresh(night)
    landed = night.scheduled_for
    if landed.tzinfo is None:
        landed = landed.replace(tzinfo=timezone.utc)
    assert landed.hour != 23
    assert 10 <= landed.hour < 22


def test_approve_rejects_non_held(db_session, make_account):
    account = make_account()
    job = PostJob(
        account_id=account.id,
        source_video_path="/tmp/x.mp4",
        status=PostJobStatus.queued,
        scheduled_for=datetime.now(timezone.utc),
    )
    db_session.add(job)
    db_session.commit()
    try:
        approve(db_session, job)
    except NotHeld:
        pass
    else:
        raise AssertionError("expected NotHeld")


def test_approve_rejects_missing_source(db_session, make_account):
    account = make_account()
    job = PostJob(
        account_id=account.id,
        source_video_path="/tmp/insta-approve-missing.mp4",
        status=PostJobStatus.awaiting_review,
        scheduled_for=datetime.now(timezone.utc),
    )
    db_session.add(job)
    db_session.commit()
    try:
        approve(db_session, job)
    except NotHeld as exc:
        assert "отсутствует" in str(exc)
    else:
        raise AssertionError("expected NotHeld")
    db_session.refresh(job)
    assert job.status is PostJobStatus.awaiting_review
