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


def test_approve_moves_past_scheduled_for_to_now(db_session, make_account):
    account = make_account()
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    job = PostJob(
        account_id=account.id,
        source_video_path="/tmp/x.mp4",
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


def test_approve_keeps_future_scheduled_for(db_session, make_account):
    account = make_account()
    future = datetime.now(timezone.utc) + timedelta(days=1)
    job = PostJob(
        account_id=account.id,
        source_video_path="/tmp/x.mp4",
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
