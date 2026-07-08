"""Job worker.

Polls the ``post_jobs`` table for due ``queued`` jobs and executes them
sequentially (one account = one process is the safe default; run multiple
worker processes if you need parallelism, never share a single process
across accounts).

Per job:
    1. Pre-checks: account active, proxy healthy, daily cap not exceeded.
    2. Uniquify the source video into ``data/videos/out``.
    3. Render a per-account caption.
    4. publisher.publish_reel (login or resume -> warmup -> upload).
    5. Persist PostLog + DailyStat. On TemporaryPublishError, exponential
       backoff up to ``settings.job_max_attempts``, then dead-letter.
       On HardPublishError, mark account ``blocked`` and alert.
"""
from __future__ import annotations

import random
import signal
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.session_manager import (
    ensure_fingerprint_and_proxy,
    maybe_rotate_session_uuids,
)
from app.behavior.idle_warmup import maybe_run_idle_warmup
from app.alerts.telegram import (
    notify_blocked,
    notify_challenge,
    notify_proxy_down,
    notify_publish_failure,
)
from app.behavior.humanizer import jitter_seconds
from app.config import settings
from app.db import (
    Account,
    AccountStatus,
    DailyStat,
    DiagnosticRunKind,
    Event,
    EventLevel,
    PostJob,
    PostJobStatus,
    PostLog,
    PostType,
    Proxy,
    SessionLocal,
    init_db,
)
from app.diagnostics.collector import DiagnosticCollector
from app.logging_setup import configure_logging, get_logger
from app.proxies.pool import ProxyError, health_check_cached, proxy_risk_score
from app.publisher.reels_publisher import (
    ActionCooldownError,
    HardPublishError,
    PublishResult,
    TemporaryPublishError,
    publish_feed_photo,
    publish_feed_video,
    publish_reel,
)
from app.publications.stats import sync_recent_publication_stats
from app.scheduler.planner import can_post_today, increment_daily_stat
from app.risk.profiles import classify_account_risk, quarantine_retry_delay
from app.video.caption_pool import render_caption
from app.video.uniquifier import uniquify
from zoneinfo import ZoneInfo

logger = get_logger(__name__)

_SHUTDOWN = False
_LAST_STATS_SYNC: datetime | None = None
_STATS_SYNC_INTERVAL = timedelta(minutes=15)


def _install_signals() -> None:
    def _stop(_signum, _frame):
        global _SHUTDOWN
        _SHUTDOWN = True
        logger.warning("worker.shutdown_requested")

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _stop)
        except (ValueError, OSError):  # pragma: no cover - non-main thread
            pass


def _claim_due_job(db: Session, now: datetime) -> Optional[PostJob]:
    """Pick the next eligible job.

    Skips jobs whose account is on an active anti-detection cooldown — those
    rows stay ``queued`` and surface again once the cooldown window expires.
    """
    base_filters = (
        (PostJob.status == PostJobStatus.queued),
        (PostJob.scheduled_for <= now),
    )
    cooldown_filter = (
        (Account.cooldown_until.is_(None)) | (Account.cooldown_until <= now)
    )

    stmt = (
        select(PostJob)
        .join(Account, Account.id == PostJob.account_id)
        .where(*base_filters, cooldown_filter)
        .order_by(PostJob.scheduled_for.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    try:
        job = db.scalar(stmt)
    except Exception:
        # SQLite doesn't support SKIP LOCKED; fall back to plain select.
        stmt_plain = (
            select(PostJob)
            .join(Account, Account.id == PostJob.account_id)
            .where(*base_filters, cooldown_filter)
            .order_by(PostJob.scheduled_for.asc())
            .limit(1)
        )
        job = db.scalar(stmt_plain)
    if job is None:
        return None
    job.status = PostJobStatus.running
    job.started_at = now
    db.commit()
    db.refresh(job)
    return job


def _account_tz(account: Account) -> ZoneInfo:
    try:
        return ZoneInfo(account.timezone)
    except Exception:
        return ZoneInfo("UTC")


def _clamp_to_active_window(account: Account, when: datetime) -> datetime:
    """If ``when`` falls outside the account's local active hours, push it
    to the start of the next active window with a small humanizing jitter.
    Keeps retries from firing at 03:00 local time after a daytime failure.
    """
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    tz = _account_tz(account)
    local = when.astimezone(tz)

    start_h = max(0, min(23, account.active_hour_start))
    end_h = max(start_h + 1, min(24, account.active_hour_end))

    hour = local.hour
    inside = start_h <= hour < end_h
    if inside:
        return when.astimezone(timezone.utc)

    if hour < start_h:
        target_local = local.replace(hour=start_h, minute=0, second=0, microsecond=0)
    else:
        next_day = local + timedelta(days=1)
        target_local = next_day.replace(hour=start_h, minute=0, second=0, microsecond=0)

    jitter_min = random.randint(5, 25)
    target_local += timedelta(minutes=jitter_min)
    return target_local.astimezone(timezone.utc)


def _backoff(attempt: int, account: Account | None = None) -> timedelta:
    """Exponential backoff with active-hours clamp.

    Returns a timedelta from *now* such that ``now + delta`` is guaranteed to
    fall inside the account's local active hours. Without the clamp, an evening
    failure could schedule the retry at 03:00 local time — a textbook bot
    fingerprint.
    """
    base = 60 * (2 ** (attempt - 1))
    delta = timedelta(seconds=jitter_seconds(base, spread=0.4))
    if account is None:
        return delta
    target = datetime.now(timezone.utc) + delta
    clamped = _clamp_to_active_window(account, target)
    return max(timedelta(seconds=30), clamped - datetime.now(timezone.utc))


def _account_proxy(db: Session, account: Account) -> Optional[Proxy]:
    if account.proxy_id is None:
        return None
    return db.get(Proxy, account.proxy_id)


def _job_post_type(job: PostJob) -> str:
    value = getattr(job, "post_type", None)
    if hasattr(value, "value"):
        return value.value
    return value or PostType.reel.value


def _on_challenge_factory(account_id: int):
    def _on(username: str, choice: object) -> None:
        notify_challenge(username, choice, account_id)
        with SessionLocal() as inner:
            acc = inner.get(Account, account_id)
            if acc is not None and acc.status == AccountStatus.active:
                acc.status = AccountStatus.challenge
                inner.commit()

    return _on


def _process_job(db: Session, job: PostJob) -> None:
    log = logger.bind(job_id=job.id, account_id=job.account_id)
    job.attempts += 1

    diag = DiagnosticCollector(
        db,
        kind=DiagnosticRunKind.publish_job,
        account_id=job.account_id,
        job_id=job.id,
    )
    on_log = diag.callback()

    def _done(status: str, summary: str) -> None:
        diag.finish(status, summary)  # type: ignore[arg-type]

    diag.info("start", f"Job #{job.id} attempt {job.attempts}")

    account = db.get(Account, job.account_id)
    if account is None:
        job.status = PostJobStatus.dead
        job.last_error = "account missing"
        db.commit()
        diag.error("account", "Account record missing")
        _done("fail", "account missing")
        return

    log = log.bind(username=account.username)
    risk_profile = classify_account_risk(account)
    log = log.bind(risk_profile=risk_profile.name)
    diag.info("account", f"@{account.username} status={account.status.value}")

    if account.status != AccountStatus.active:
        job.status = PostJobStatus.cancelled
        job.last_error = f"account status: {account.status.value}"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        log.warning("worker.account_not_active", status=account.status.value)
        diag.warn("account", f"Account not active: {account.status.value}")
        _done("fail", job.last_error)
        return

    if not can_post_today(db, account):
        job.status = PostJobStatus.queued
        job.scheduled_for = datetime.now(timezone.utc) + timedelta(hours=2)
        db.commit()
        log.info("worker.daily_cap_reached_reschedule")
        diag.info("cap", "Daily post cap reached — rescheduled +2h")
        _done("warn", "daily cap reached")
        return

    proxy = _account_proxy(db, account)
    if proxy is None:
        diag.error("proxy", "No proxy assigned")
        _done("fail", "no proxy assigned")
        _fail_hard(db, job, account, "no proxy assigned")
        return

    diag.info("proxy", f"Checking proxy {proxy.label}")
    try:
        snapshot = health_check_cached(proxy.url)
    except ProxyError as exc:
        proxy.is_healthy = False
        proxy.last_checked_at = datetime.now(timezone.utc)
        db.commit()
        notify_proxy_down(proxy.label, str(exc))
        diag.error("proxy", str(exc))
        _done("fail", f"proxy unhealthy: {exc}")
        _fail_temporary(db, job, account, f"proxy unhealthy: {exc}")
        return
    else:
        # Best-effort persistence of geo info between full health-check runs.
        if snapshot.ip:
            proxy.last_known_ip = snapshot.ip
        if snapshot.country:
            if proxy.country and proxy.country.upper() != snapshot.country.upper():
                log.warning(
                    "worker.proxy_geo_mismatch",
                    advertised=proxy.country,
                    actual=snapshot.country,
                )
                diag.warn(
                    "proxy",
                    f"Geo mismatch advertised={proxy.country} actual={snapshot.country}",
                )
            proxy.last_geo_country = snapshot.country
        proxy.is_healthy = True
        proxy.last_checked_at = datetime.now(timezone.utc)
        risk = proxy_risk_score(snapshot, advertised_country=proxy.country)
        if risk >= 0.25:
            db.add(
                Event(
                    account_id=account.id,
                    level=EventLevel.warn,
                    kind="proxy.unstable",
                    message=f"Proxy {proxy.label} risk score={risk:.2f}",
                )
            )
            diag.warn("proxy", f"Proxy risk score={risk:.2f}")
        db.commit()
        diag.info(
            "proxy",
            f"Proxy healthy ip={snapshot.ip or '?'} instagram_ok={snapshot.instagram_reachable}",
        )

    fingerprint = ensure_fingerprint_and_proxy(account.username, country=proxy.country or "US")
    rotated, fingerprint = maybe_rotate_session_uuids(
        account.username, fingerprint, account.last_session_rotation_at
    )
    if rotated:
        account.last_session_rotation_at = datetime.now(timezone.utc)
        db.commit()
        diag.info("session", "Rotated client session UUIDs")
    elif account.last_session_rotation_at is None:
        # First time we touch this account post-upgrade — stamp now so the
        # 3–7 day clock starts ticking from a known origin.
        account.last_session_rotation_at = datetime.now(timezone.utc)
        db.commit()

    src = Path(job.source_video_path)
    if not src.exists():
        diag.error("media", f"Source missing: {src}")
        _done("fail", f"source missing: {src}")
        _fail_hard(db, job, account, f"source missing: {src}")
        return

    post_type = _job_post_type(job)
    diag.info("media", f"Post type={post_type} source={src.name}")
    if post_type == PostType.reel.value:
        out_path = settings.video_out_dir / f"{account.username}_{job.id}_{int(time.time())}.mp4"
        try:
            # Mirror is opt-in here; the inner ``random_params`` rolls a 5%
            # probability so most posts stay un-flipped (preserves text overlays).
            uniquify(src, out_path, allow_mirror=True, on_log=on_log)
        except Exception as exc:
            log.exception("worker.uniquify_failed")
            diag.error("uniquify", str(exc))
            _done("fail", f"uniquify failed: {exc}")
            _fail_temporary(db, job, account, f"uniquify failed: {exc}")
            return
    else:
        out_path = src
        diag.info("uniquify", "Skipped (not a reel)")

    caption = render_caption(
        account_username=account.username,
        template=job.caption_template,
        seed=f"{account.username}:{job.id}:{src.name}",
        profile=account.caption_profile,
        timezone=account.timezone,
        anti_repeat=True,
    )
    diag.info("caption", f"Caption ready ({len(caption)} chars)")

    try:
        common = dict(
            username=account.username,
            password=account.password,
            fingerprint=fingerprint,
            proxy_url=proxy.url,
            caption=caption,
            on_challenge=_on_challenge_factory(account.id),
            totp_seed=account.totp_seed,
            session_id=account.session_id,
            email=account.email,
            email_password=account.email_password,
            on_log=on_log,
        )
        if post_type == PostType.feed_photo.value:
            result: PublishResult = publish_feed_photo(image_path=out_path, **common)
        elif post_type == PostType.feed_video.value:
            result = publish_feed_video(video_path=out_path, **common)
        else:
            result = publish_reel(
                video_path=out_path,
                do_warmup=True,
                warmup_intensity=random.choice(["light", "normal", "normal", "heavy"]),
                **common,
            )
    except ActionCooldownError as exc:
        cooldown_hours = random.randint(24, 48)
        cooldown_until = datetime.now(timezone.utc) + timedelta(hours=cooldown_hours)
        account.status = AccountStatus.cooldown
        account.cooldown_until = cooldown_until
        log.warning(
            "worker.action_cooldown",
            error=str(exc),
            cooldown_hours=cooldown_hours,
            cooldown_until=cooldown_until.isoformat(),
        )
        diag.warn("publish", f"Action cooldown {cooldown_hours}h: {exc}")
        db.add(
            Event(
                account_id=account.id,
                level=EventLevel.warn,
                kind="account_cooldown",
                message=(
                    f"action cooldown {cooldown_hours}h after FeedbackRequired: {exc}"
                ),
            )
        )
        _record_post_log(
            db, job, account, success=False, error=str(exc),
            final_video=out_path, final_caption=caption,
        )
        increment_daily_stat(db, account, success=False)
        # Re-queue the job after cooldown so it isn't lost.
        job.status = PostJobStatus.queued
        job.last_error = f"cooldown: {exc}"
        job.next_attempt_at = cooldown_until + timedelta(minutes=random.randint(5, 25))
        job.scheduled_for = job.next_attempt_at
        db.commit()
        _done("warn", f"cooldown: {exc}")
        return
    except HardPublishError as exc:
        log.error("worker.hard_publish_error", error=str(exc))
        diag.error("publish", str(exc))
        account.status = AccountStatus.blocked
        notify_blocked(account.username, account.id, str(exc))
        _record_post_log(db, job, account, success=False, error=str(exc), final_video=out_path, final_caption=caption)
        increment_daily_stat(db, account, success=False)
        job.status = PostJobStatus.dead
        job.last_error = str(exc)
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        _done("fail", str(exc))
        return
    except TemporaryPublishError as exc:
        log.warning("worker.temp_publish_error", error=str(exc), attempt=job.attempts)
        diag.warn("publish", str(exc))
        notify_publish_failure(account.username, account.id, str(exc), job.attempts)
        _record_post_log(db, job, account, success=False, error=str(exc), final_video=out_path, final_caption=caption)
        increment_daily_stat(db, account, success=False)
        if _should_quarantine(account, str(exc), job.attempts):
            _enter_quarantine(db, job, account, reason=str(exc))
            _done("warn", f"quarantine: {exc}")
            return
        _fail_temporary(db, job, account, str(exc))
        _done("warn", str(exc))
        return
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("worker.unexpected")
        diag.error("publish", f"unexpected: {exc}")
        _fail_temporary(db, job, account, f"unexpected: {exc}")
        _done("fail", f"unexpected: {exc}")
        return

    _record_post_log(
        db,
        job,
        account,
        success=True,
        error=None,
        final_video=Path(result.final_video_path),
        final_caption=result.final_caption,
        media_id=result.media_id,
        media_code=result.media_code,
    )
    increment_daily_stat(db, account, success=True)
    account.last_publish_at = datetime.now(timezone.utc)
    job.status = PostJobStatus.done
    job.finished_at = datetime.now(timezone.utc)
    job.last_error = None
    db.commit()
    log.info("worker.job_done", media_id=result.media_id)
    diag.info("done", f"Published media_id={result.media_id}")
    _done("ok", f"Published media_id={result.media_id}")


def _fail_temporary(db: Session, job: PostJob, account: Account, message: str) -> None:
    if job.attempts >= settings.job_max_attempts:
        job.status = PostJobStatus.dead
        job.finished_at = datetime.now(timezone.utc)
        job.last_error = message
        db.add(
            Event(
                account_id=account.id,
                level=EventLevel.error,
                kind="job_dead",
                message=f"job {job.id} dead-lettered after {job.attempts} attempts: {message}",
            )
        )
        db.commit()
        return

    job.status = PostJobStatus.queued
    job.last_error = message
    job.next_attempt_at = datetime.now(timezone.utc) + _backoff(job.attempts, account)
    job.scheduled_for = job.next_attempt_at
    db.commit()


def _should_quarantine(account: Account, message: str, attempts: int) -> bool:
    msg = message.lower()
    auth_hints = ("login", "challenge", "checkpoint", "suspicious", "feedback", "too many")
    if any(h in msg for h in auth_hints) and attempts >= 2:
        return True
    if account.status in (AccountStatus.challenge, AccountStatus.cooldown):
        return True
    return False


def _enter_quarantine(db: Session, job: PostJob, account: Account, *, reason: str) -> None:
    until = quarantine_retry_delay(account)
    account.status = AccountStatus.paused
    job.status = PostJobStatus.queued
    job.last_error = f"quarantine: {reason}"
    job.next_attempt_at = until
    job.scheduled_for = until
    db.add(
        Event(
            account_id=account.id,
            level=EventLevel.warn,
            kind="risk.quarantine",
            message=f"Account moved to quarantine until {until.isoformat()} ({reason})",
        )
    )
    db.commit()


def _fail_hard(db: Session, job: PostJob, account: Account, message: str) -> None:
    job.status = PostJobStatus.dead
    job.last_error = message
    job.finished_at = datetime.now(timezone.utc)
    db.add(
        Event(
            account_id=account.id,
            level=EventLevel.error,
            kind="job_hard_fail",
            message=f"job {job.id} hard-failed: {message}",
        )
    )
    db.commit()


def _record_post_log(
    db: Session,
    job: PostJob,
    account: Account,
    *,
    success: bool,
    error: Optional[str],
    final_video: Path,
    final_caption: str,
    media_id: Optional[str] = None,
    media_code: Optional[str] = None,
) -> None:
    db.add(
        PostLog(
            job_id=job.id,
            account_id=account.id,
            success=success,
            error=error,
            final_video_path=str(final_video),
            final_caption=final_caption,
            media_id=media_id,
            media_code=media_code,
            post_type=_job_post_type(job),
        )
    )


def _maybe_sync_publication_stats(now: datetime) -> None:
    global _LAST_STATS_SYNC
    if _LAST_STATS_SYNC is not None and now - _LAST_STATS_SYNC < _STATS_SYNC_INTERVAL:
        return
    _LAST_STATS_SYNC = now
    with SessionLocal() as db:
        count = sync_recent_publication_stats(db, now=now)
        if count:
            logger.info("worker.publication_stats_synced", count=count)


def run() -> None:
    """Main loop: poll DB, claim job, run, sleep, repeat."""
    configure_logging()
    init_db()
    _install_signals()

    logger.info("worker.start", poll_sec=settings.worker_poll_interval_sec)

    while not _SHUTDOWN:
        now = datetime.now(timezone.utc)
        try:
            with SessionLocal() as db:
                job = _claim_due_job(db, now)
                if job is not None:
                    _process_job(db, job)
                else:
                    try:
                        _maybe_sync_publication_stats(now)
                    except Exception as exc:  # noqa: BLE001 - stats sync is best effort
                        logger.warning("worker.publication_stats_sync_failed", error=str(exc))
                    # Idle tick: with low probability, pick an inactive account
                    # and run a publish-less warmup so its traffic profile
                    # doesn't look like "online only when posting".
                    try:
                        maybe_run_idle_warmup()
                    except Exception as exc:  # noqa: BLE001 - never crash the loop
                        logger.warning("worker.idle_warmup_failed", error=str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("worker.loop_error", error=str(exc))

        sleep_for = jitter_seconds(settings.worker_poll_interval_sec, spread=0.3)
        end = time.monotonic() + sleep_for
        while time.monotonic() < end:
            if _SHUTDOWN:
                break
            time.sleep(0.5)

    logger.info("worker.stopped")
