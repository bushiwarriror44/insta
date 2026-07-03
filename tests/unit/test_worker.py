"""Tests for app.scheduler.worker."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.accounts.session_manager import HardCheckpoint
from app.config import settings
from app.db import (
    Account,
    AccountStatus,
    DailyStat,
    Event,
    PostJob,
    PostJobStatus,
    PostType,
    PostLog,
    Proxy,
)
from app.proxies.pool import HealthSnapshot, ProxyError
from app.publisher.reels_publisher import (
    ActionCooldownError,
    HardPublishError,
    PublishResult,
    TemporaryPublishError,
)
from app.scheduler import worker as worker_module


def _ok_snapshot():
    return HealthSnapshot(
        ok=True,
        ip="1.1.1.1",
        country="US",
        instagram_reachable=True,
        checked_at=datetime.now(timezone.utc),
    )


@pytest.fixture()
def worker_env(monkeypatch, app_env):
    """Patch out everything network-y inside the worker module."""
    monkeypatch.setattr(worker_module, "health_check_cached", lambda url: _ok_snapshot())
    monkeypatch.setattr(worker_module, "ensure_fingerprint_and_proxy",
                        lambda username, country="US": _Fingerprint())
    monkeypatch.setattr(
        worker_module, "maybe_rotate_session_uuids",
        lambda username, fp, last: (False, fp),
    )
    monkeypatch.setattr(worker_module, "maybe_run_idle_warmup", lambda *a, **k: False)
    monkeypatch.setattr(worker_module, "uniquify", _fake_uniquify)
    monkeypatch.setattr(worker_module, "render_caption", lambda **kwargs: "test caption")
    monkeypatch.setattr(worker_module, "notify_blocked", lambda *a, **k: None)
    monkeypatch.setattr(worker_module, "notify_challenge", lambda *a, **k: None)
    monkeypatch.setattr(worker_module, "notify_proxy_down", lambda *a, **k: None)
    monkeypatch.setattr(worker_module, "notify_publish_failure", lambda *a, **k: None)
    monkeypatch.setattr(worker_module, "jitter_seconds", lambda *_a, **_k: 0.0)
    return app_env


class _Fingerprint:
    def __init__(self):
        self.country = "US"


def _fake_uniquify(src, dst, *, allow_mirror=False, **_kwargs):
    from pathlib import Path

    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    Path(dst).write_bytes(b"x")
    return None


def _make_video(app_env, name="src.mp4"):
    path = app_env.video_source_dir / name
    path.write_bytes(b"x")
    return path


def _make_image(app_env, name="src.jpg"):
    path = app_env.video_source_dir / name
    path.write_bytes(b"x")
    return path


def _make_job(
    db_session,
    account,
    video_path,
    *,
    when=None,
    status=PostJobStatus.queued,
    post_type=PostType.reel,
):
    job = PostJob(
        account_id=account.id,
        source_video_path=str(video_path),
        post_type=post_type,
        scheduled_for=when or (datetime.now(timezone.utc) - timedelta(minutes=1)),
        status=status,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def test_claim_due_job_picks_earliest(worker_env, db_session, make_account):
    account = make_account()
    earliest = _make_job(
        db_session, account, _make_video(worker_env, "a.mp4"),
        when=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    _make_job(
        db_session, account, _make_video(worker_env, "b.mp4"),
        when=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    claimed = worker_module._claim_due_job(db_session, datetime.now(timezone.utc))
    assert claimed.id == earliest.id
    assert claimed.status == PostJobStatus.running


def test_claim_no_due_jobs_returns_none(worker_env, db_session, make_account):
    account = make_account()
    _make_job(
        db_session, account, _make_video(worker_env, "a.mp4"),
        when=datetime.now(timezone.utc) + timedelta(hours=2),
    )
    assert worker_module._claim_due_job(db_session, datetime.now(timezone.utc)) is None


def test_backoff_grows_exponentially():
    a = worker_module._backoff(1)
    b = worker_module._backoff(3)
    assert a < b


def test_backoff_clamps_to_active_window(worker_env, db_session, make_account):
    """A retry whose naive backoff lands at 03:00 local time must be pushed
    to the start of the next active window."""
    from datetime import datetime as _dt
    import app.scheduler.worker as wm

    # Account active 10:00–22:00 UTC. We freeze "now" at 23:30 UTC so that
    # a 60s exponential backoff would otherwise fall at ~23:31 (outside window).
    account = make_account(timezone="UTC", active_hour_start=10, active_hour_end=22)

    real_now = _dt.now

    class _FrozenDateTime(_dt):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return _dt(2026, 5, 8, 23, 30, 0, tzinfo=tz or timezone.utc)

    import datetime as _datetime_mod

    orig_dt = wm.datetime
    wm.datetime = _FrozenDateTime  # type: ignore[assignment]
    try:
        delta = wm._backoff(1, account)
    finally:
        wm.datetime = orig_dt  # type: ignore[assignment]

    next_attempt = _dt(2026, 5, 8, 23, 30, 0, tzinfo=timezone.utc) + delta
    # Must land inside the next-day's [10:00, 22:00) window.
    assert next_attempt.hour >= 10 and next_attempt.hour < 22


def test_process_job_happy_path(worker_env, db_session, make_account, monkeypatch):
    account = make_account()
    video = _make_video(worker_env, "happy.mp4")
    job = _make_job(db_session, account, video)

    def _publish_ok(**kwargs):
        return PublishResult(
            media_id="MID",
            media_code="CODE",
            final_video_path=video,
            final_caption="cap",
        )

    monkeypatch.setattr(worker_module, "publish_reel", _publish_ok)

    job.status = PostJobStatus.running
    db_session.commit()
    worker_module._process_job(db_session, job)

    db_session.refresh(job)
    assert job.status == PostJobStatus.done
    log = db_session.scalar(select(PostLog).where(PostLog.job_id == job.id))
    assert log is not None
    assert log.success is True
    assert log.media_id == "MID"
    stat = db_session.scalar(
        select(DailyStat).where(DailyStat.account_id == account.id)
    )
    assert stat.posts_count == 1
    db_session.refresh(account)
    assert account.last_publish_at is not None


def test_process_job_feed_photo_uses_photo_publisher(worker_env, db_session, make_account, monkeypatch):
    account = make_account()
    image = _make_image(worker_env, "photo.jpg")
    job = _make_job(db_session, account, image, post_type=PostType.feed_photo)
    captured: dict = {}

    def _publish_photo(**kwargs):
        captured.update(kwargs)
        return PublishResult(media_id="PHOTO", media_code="P", final_video_path=image, final_caption="cap")

    monkeypatch.setattr(worker_module, "publish_feed_photo", _publish_photo)
    worker_module._process_job(db_session, job)

    db_session.refresh(job)
    assert job.status == PostJobStatus.done
    assert captured["image_path"] == image
    log = db_session.scalar(select(PostLog).where(PostLog.job_id == job.id))
    assert log.post_type == "feed_photo"
    assert log.media_id == "PHOTO"


def test_process_job_feed_video_uses_video_publisher(worker_env, db_session, make_account, monkeypatch):
    account = make_account()
    video = _make_video(worker_env, "feed.mp4")
    job = _make_job(db_session, account, video, post_type=PostType.feed_video)
    captured: dict = {}

    def _publish_video(**kwargs):
        captured.update(kwargs)
        return PublishResult(media_id="VID", media_code="V", final_video_path=video, final_caption="cap")

    monkeypatch.setattr(worker_module, "publish_feed_video", _publish_video)
    worker_module._process_job(db_session, job)

    db_session.refresh(job)
    assert job.status == PostJobStatus.done
    assert captured["video_path"] == video
    log = db_session.scalar(select(PostLog).where(PostLog.job_id == job.id))
    assert log.post_type == "feed_video"
    assert log.media_id == "VID"


def test_process_job_account_not_active_cancels(worker_env, db_session, make_account):
    account = make_account(status=AccountStatus.paused)
    video = _make_video(worker_env)
    job = _make_job(db_session, account, video)
    worker_module._process_job(db_session, job)
    db_session.refresh(job)
    assert job.status == PostJobStatus.cancelled


def test_process_job_daily_cap_reached_reschedules(worker_env, db_session, make_account):
    account = make_account(daily_post_cap=1)
    today = datetime.now(timezone.utc).date().isoformat()
    db_session.add(DailyStat(account_id=account.id, date_key=today, posts_count=1))
    db_session.commit()

    video = _make_video(worker_env)
    job = _make_job(db_session, account, video)
    worker_module._process_job(db_session, job)
    db_session.refresh(job)
    assert job.status == PostJobStatus.queued
    # SQLite strips tzinfo on read; compare naive-with-naive.
    naive_now = datetime.now(timezone.utc).replace(tzinfo=None)
    sched = job.scheduled_for
    if sched.tzinfo is not None:
        sched = sched.replace(tzinfo=None)
    assert sched > naive_now


def test_process_job_no_proxy_dead_letters(worker_env, db_session, make_account):
    account = make_account()
    account.proxy_id = None
    db_session.commit()
    video = _make_video(worker_env)
    job = _make_job(db_session, account, video)
    worker_module._process_job(db_session, job)
    db_session.refresh(job)
    assert job.status == PostJobStatus.dead


def test_process_job_proxy_unhealthy_temporary(worker_env, db_session, make_account, monkeypatch):
    account = make_account()
    video = _make_video(worker_env)
    job = _make_job(db_session, account, video)

    def _bad_health(_url, **_kwargs):
        raise ProxyError("down")

    monkeypatch.setattr(worker_module, "health_check_cached", _bad_health)
    worker_module._process_job(db_session, job)
    db_session.refresh(job)
    assert job.status == PostJobStatus.queued
    assert job.attempts == 1
    proxy = db_session.get(Proxy, account.proxy_id)
    assert proxy.is_healthy is False


def test_process_job_missing_source_dead(worker_env, db_session, make_account):
    account = make_account()
    job = _make_job(db_session, account, worker_env.video_source_dir / "ghost.mp4")
    worker_module._process_job(db_session, job)
    db_session.refresh(job)
    assert job.status == PostJobStatus.dead


def test_process_job_uniquify_fails_temporary(worker_env, db_session, make_account, monkeypatch):
    account = make_account()
    video = _make_video(worker_env)
    job = _make_job(db_session, account, video)

    def _bad_uniquify(*_a, **_k):
        raise RuntimeError("ffmpeg crash")

    monkeypatch.setattr(worker_module, "uniquify", _bad_uniquify)
    worker_module._process_job(db_session, job)
    db_session.refresh(job)
    assert job.status == PostJobStatus.queued
    assert job.attempts == 1


def test_process_job_hard_publish_blocks_account(worker_env, db_session, make_account, monkeypatch):
    account = make_account()
    video = _make_video(worker_env)
    job = _make_job(db_session, account, video)

    def _publish(**kwargs):
        raise HardPublishError("checkpoint")

    monkeypatch.setattr(worker_module, "publish_reel", _publish)
    worker_module._process_job(db_session, job)
    db_session.refresh(job)
    db_session.refresh(account)
    assert job.status == PostJobStatus.dead
    assert account.status == AccountStatus.blocked


def test_process_job_temporary_then_dead_after_max_attempts(
    worker_env, db_session, make_account, monkeypatch
):
    monkeypatch.setattr(settings, "job_max_attempts", 2)
    account = make_account()
    video = _make_video(worker_env)
    job = _make_job(db_session, account, video)

    def _publish(**kwargs):
        raise TemporaryPublishError("rate")

    monkeypatch.setattr(worker_module, "publish_reel", _publish)

    worker_module._process_job(db_session, job)
    db_session.refresh(job)
    assert job.status == PostJobStatus.queued
    assert job.attempts == 1

    job.status = PostJobStatus.running
    db_session.commit()
    worker_module._process_job(db_session, job)
    db_session.refresh(job)
    assert job.status == PostJobStatus.dead
    assert job.attempts == 2
    events = db_session.scalars(select(Event).where(Event.kind == "job_dead")).all()
    assert events


def test_run_loop_exits_on_shutdown_flag(worker_env, monkeypatch):
    monkeypatch.setattr(worker_module, "_SHUTDOWN", True)
    monkeypatch.setattr(settings, "worker_poll_interval_sec", 1)
    # Should return promptly without doing any work.
    worker_module.run()


def test_action_cooldown_applies_24_to_48h_cooldown(
    worker_env, db_session, make_account, monkeypatch
):
    """An ActionCooldownError must NOT mark the account ``blocked``; it should
    set ``status=cooldown`` with ``cooldown_until`` 24-48h in the future and
    requeue the job for after the cooldown expires."""
    account = make_account()
    video = _make_video(worker_env, "cd.mp4")
    job = _make_job(db_session, account, video)

    def _publish(**kwargs):
        raise ActionCooldownError("feedback_required: spam")

    monkeypatch.setattr(worker_module, "publish_reel", _publish)

    worker_module._process_job(db_session, job)
    db_session.refresh(job)
    db_session.refresh(account)

    assert account.status == AccountStatus.cooldown
    assert account.cooldown_until is not None
    cooldown = account.cooldown_until
    if cooldown.tzinfo is None:
        cooldown = cooldown.replace(tzinfo=timezone.utc)
    delta_hours = (cooldown - datetime.now(timezone.utc)).total_seconds() / 3600
    assert 23 <= delta_hours <= 49  # 24-48h plus rounding wobble

    # Job is re-queued (not dead) and points past the cooldown.
    assert job.status == PostJobStatus.queued
    sched = job.scheduled_for
    if sched.tzinfo is None:
        sched = sched.replace(tzinfo=timezone.utc)
    assert sched >= cooldown


def test_claim_due_job_skips_cooldown_accounts(worker_env, db_session, make_account):
    """A queued job must be ignored while its account is still on cooldown."""
    account = make_account()
    account.cooldown_until = datetime.now(timezone.utc) + timedelta(hours=12)
    db_session.commit()
    _make_job(
        db_session, account, _make_video(worker_env, "skipme.mp4"),
        when=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    assert worker_module._claim_due_job(db_session, datetime.now(timezone.utc)) is None


def test_claim_due_job_picks_up_after_cooldown_expires(worker_env, db_session, make_account):
    account = make_account()
    account.cooldown_until = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.commit()
    job = _make_job(
        db_session, account, _make_video(worker_env, "cdexp.mp4"),
        when=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    claimed = worker_module._claim_due_job(db_session, datetime.now(timezone.utc))
    assert claimed is not None and claimed.id == job.id


def test_publish_receives_totp_seed_and_email(
    worker_env, db_session, make_account, monkeypatch
):
    """Worker must forward ``totp_seed``/``email`` from the Account row to
    publish_reel so 2FA and email-challenge can resolve unattended."""
    account = make_account()
    account.totp_seed = "JBSWY3DPEHPK3PXP"
    account.email = "user@example.com"
    account.email_password = "imap-pw"
    db_session.commit()

    video = _make_video(worker_env, "totp.mp4")
    job = _make_job(db_session, account, video)

    captured: dict = {}

    def _publish(**kwargs):
        captured.update(kwargs)
        return PublishResult(
            media_id="MID", media_code="C",
            final_video_path=video, final_caption="cap",
        )

    monkeypatch.setattr(worker_module, "publish_reel", _publish)
    worker_module._process_job(db_session, job)

    assert captured.get("totp_seed") == "JBSWY3DPEHPK3PXP"
    assert captured.get("email") == "user@example.com"
    assert captured.get("email_password") == "imap-pw"


def test_publish_receives_session_id(worker_env, db_session, make_account, monkeypatch):
    account = make_account()
    account.session_id = "s" * 40
    db_session.commit()

    video = _make_video(worker_env, "sess.mp4")
    job = _make_job(db_session, account, video)

    captured: dict = {}

    def _publish(**kwargs):
        captured.update(kwargs)
        return PublishResult(
            media_id="MID",
            media_code="C",
            final_video_path=video,
            final_caption="cap",
        )

    monkeypatch.setattr(worker_module, "publish_reel", _publish)
    worker_module._process_job(db_session, job)

    assert captured.get("session_id") == "s" * 40


def test_temporary_auth_signal_enters_quarantine(
    worker_env, db_session, make_account, monkeypatch
):
    account = make_account()
    video = _make_video(worker_env, "q.mp4")
    job = _make_job(db_session, account, video)

    def _publish(**kwargs):
        raise TemporaryPublishError("challenge required after login")

    monkeypatch.setattr(worker_module, "publish_reel", _publish)
    job.attempts = 1
    db_session.commit()
    worker_module._process_job(db_session, job)

    db_session.refresh(account)
    db_session.refresh(job)
    assert account.status == AccountStatus.paused
    assert "quarantine" in (job.last_error or "")
    event = db_session.scalar(select(Event).where(Event.kind == "risk.quarantine"))
    assert event is not None


def test_proxy_unstable_event_created_on_geo_mismatch(
    worker_env, db_session, make_account, monkeypatch
):
    account = make_account()
    video = _make_video(worker_env, "proxyrisk.mp4")
    job = _make_job(db_session, account, video)

    def _snapshot(_url):
        return HealthSnapshot(
            ok=True,
            ip="2.2.2.2",
            country="NL",
            instagram_reachable=True,
            checked_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr(worker_module, "health_check_cached", _snapshot)
    monkeypatch.setattr(
        worker_module,
        "publish_reel",
        lambda **kwargs: PublishResult(
            media_id="M1",
            media_code="C1",
            final_video_path=video,
            final_caption="cap",
        ),
    )
    worker_module._process_job(db_session, job)
    evt = db_session.scalar(select(Event).where(Event.kind == "proxy.unstable"))
    assert evt is not None
