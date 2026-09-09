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
from app.geo.country_codes import countries_mismatch
from app.geo.timezone_normalize import timezone_from_proxy
from app.proxies.pool import ProxyError, HealthCheckScope, health_check_cached, proxy_risk_score
from app.publisher.reels_publisher import (
    ActionCooldownError,
    HardPublishError,
    PublishResult,
    TemporaryPublishError,
    publish_feed_photo,
    publish_feed_video,
    publish_reel,
)
from app.publisher.tiktok_publisher import publish_tiktok
from app.publisher.youtube_publisher import publish_youtube_short
from app.db.models import Platform
from app.services.composing import claim_due_composition, run_composition
from app.services.generation import claim_due_generation_job, run_generation_job
from app.services.planning import claim_due_plan_job, run_plan_job
from app.publications.stats import sync_recent_publication_stats
from app.scheduler.heartbeat import beat
from app.scheduler.planner import can_post_today, increment_daily_stat
from app.risk.profiles import classify_account_risk, quarantine_retry_delay
from app.video.caption_pool import render_caption
from app.video.uniquifier import random_params, uniquify
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

    for sig in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGBREAK", None)):
        if sig is None:
            continue
        try:
            signal.signal(sig, _stop)
        except (ValueError, OSError):  # pragma: no cover - non-main thread
            pass


def _claim_due_job(db: Session, now: datetime) -> Optional[PostJob]:
    """Pick the next eligible job.

    Skips jobs whose account is operator-paused or still on an anti-detection
    cooldown. Those rows stay ``queued`` until pause is lifted or the cooldown
    window expires.
    """
    base_filters = (
        (PostJob.status == PostJobStatus.queued),
        (PostJob.scheduled_for <= now),
    )
    cooldown_filter = (
        (Account.cooldown_until.is_(None)) | (Account.cooldown_until <= now)
    )
    paused_filter = Account.status != AccountStatus.paused

    stmt = (
        select(PostJob)
        .join(Account, Account.id == PostJob.account_id)
        .where(*base_filters, cooldown_filter, paused_filter)
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
            .where(*base_filters, cooldown_filter, paused_filter)
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


def _account_platform(account: Account) -> Platform:
    value = getattr(account, "platform", None)
    if isinstance(value, Platform):
        return value
    if value:
        try:
            return Platform(value)
        except ValueError:
            pass
    return Platform.instagram


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

    diag.info("start", f"Задача #{job.id}, попытка {job.attempts}")

    account = db.get(Account, job.account_id)
    if account is None:
        job.status = PostJobStatus.dead
        job.last_error = "account missing"
        db.commit()
        diag.error("account", "Запись аккаунта отсутствует")
        _done("fail", "account missing")
        return

    log = log.bind(username=account.username)
    risk_profile = classify_account_risk(account)
    log = log.bind(risk_profile=risk_profile.name)
    diag.info("account", f"@{account.username} статус={account.status.value}")

    # Soft-block cooldown expired → restore active so claimable jobs are not cancelled.
    if account.status == AccountStatus.cooldown:
        now = datetime.now(timezone.utc)
        until = account.cooldown_until
        if until is not None and until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        if until is None or until <= now:
            account.status = AccountStatus.active
            account.cooldown_until = None
            db.commit()
            log.info("worker.cooldown_expired_restored")
            diag.info("account", "Cooldown истёк — статус active")

    if account.status != AccountStatus.active:
        job.status = PostJobStatus.queued
        job.last_error = f"account status: {account.status.value}"
        db.commit()
        log.warning("worker.account_not_active", status=account.status.value)
        diag.warn("account", f"Аккаунт неактивен: {account.status.value}")
        _done("warn", job.last_error)
        return

    now = datetime.now(timezone.utc)
    due_in_window = _clamp_to_active_window(account, now)
    if due_in_window > now:
        job.status = PostJobStatus.queued
        job.scheduled_for = due_in_window
        db.commit()
        log.info("worker.outside_active_hours_reschedule")
        diag.info("hours", "Вне часов активности — перенос в окно")
        _done("warn", "outside active hours")
        return

    if not can_post_today(db, account):
        job.status = PostJobStatus.queued
        job.scheduled_for = _clamp_to_active_window(
            account, datetime.now(timezone.utc) + timedelta(hours=2)
        )
        db.commit()
        log.info("worker.daily_cap_reached_reschedule")
        diag.info("cap", "Дневной лимит публикаций — перенос на +2 ч")
        _done("warn", "daily cap reached")
        return

    proxy = _account_proxy(db, account)
    if proxy is None:
        diag.error("proxy", "Прокси не назначен")
        _done("fail", "no proxy assigned")
        _fail_hard(db, job, account, "no proxy assigned")
        return

    diag.info("proxy", f"Проверка прокси {proxy.label}")
    try:
        snapshot = health_check_cached(proxy.url, scope=HealthCheckScope.MINIMAL)
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
            if countries_mismatch(proxy.country, snapshot.country):
                log.warning(
                    "worker.proxy_geo_mismatch",
                    advertised=proxy.country,
                    actual=snapshot.country,
                )
                diag.warn(
                    "proxy",
                    f"Несовпадение гео: указано {proxy.country}, фактически {snapshot.country}",
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
            diag.warn("proxy", f"Риск прокси={risk:.2f}")
        db.commit()
        diag.info(
            "proxy",
            f"Прокси исправен ip={snapshot.ip or '?'}",
        )

    platform = _account_platform(account)
    fingerprint = None
    if platform == Platform.instagram:
        fingerprint = ensure_fingerprint_and_proxy(
            account.username,
            country=proxy.country or "US",
            timezone_id=timezone_from_proxy(proxy.timezone, proxy.country),
        )
        rotated, fingerprint = maybe_rotate_session_uuids(
            account.username, fingerprint, account.last_session_rotation_at
        )
        if rotated:
            account.last_session_rotation_at = datetime.now(timezone.utc)
            db.commit()
            diag.info("session", "Обновлены UUID клиентской сессии")
        elif account.last_session_rotation_at is None:
            account.last_session_rotation_at = datetime.now(timezone.utc)
            db.commit()

    src = Path(job.source_video_path)
    if not src.exists():
        diag.error("media", f"Исходный файл отсутствует: {src}")
        _done("fail", f"source missing: {src}")
        _fail_hard(db, job, account, f"source missing: {src}")
        return

    post_type = _job_post_type(job)
    diag.info("media", f"Тип публикации={post_type} файл={src.name}")
    uniquify_types = {PostType.reel.value, PostType.youtube_short.value, PostType.tiktok.value}
    if post_type in uniquify_types:
        out_path = settings.video_out_dir / f"{account.username}_{job.id}_{int(time.time())}.mp4"
        try:
            uniquify(
                src,
                out_path,
                params=random_params(
                    allow_mirror=True,
                    assume_tiktok_watermark=(post_type == PostType.tiktok.value),
                ),
                allow_mirror=True,
                on_log=on_log,
            )
        except Exception as exc:
            log.exception("worker.uniquify_failed")
            diag.error("uniquify", str(exc))
            _done("fail", f"uniquify failed: {exc}")
            _fail_temporary(db, job, account, f"uniquify failed: {exc}")
            return
    else:
        out_path = src
        diag.info("uniquify", "Пропущено (не видео-ролик)")

    caption = render_caption(
        account_username=account.username,
        template=job.caption_template,
        seed=f"{account.username}:{job.id}:{src.name}",
        profile=account.caption_profile,
        timezone=account.timezone,
        anti_repeat=True,
    )
    diag.info("caption", f"Подпись готова ({len(caption)} симв.)")

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
        elif post_type == PostType.youtube_short.value or _account_platform(account) == Platform.youtube:
            result = publish_youtube_short(
                username=account.username,
                video_path=out_path,
                title=job.title or caption[:100],
                description=job.description or caption,
                tags=job.tags or "",
                privacy=job.privacy or "public",
                proxy_url=proxy.url,
                fingerprint=fingerprint,
                on_log=on_log,
            )
        elif post_type == PostType.tiktok.value or _account_platform(account) == Platform.tiktok:
            result = publish_tiktok(
                username=account.username,
                video_path=out_path,
                title=job.title or caption[:100],
                description=job.description or caption,
                tags=job.tags or "",
                proxy_url=proxy.url,
                fingerprint=fingerprint,
                on_log=on_log,
            )
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
        diag.warn("publish", f"Пауза действий {cooldown_hours} ч: {exc}")
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
        diag.error("publish", f"неожиданная ошибка: {exc}")
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
    diag.info("done", f"Опубликовано media_id={result.media_id}")
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
    account.status = AccountStatus.cooldown
    account.cooldown_until = until
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
    configure_logging()
    init_db()
    _install_signals()

    logger.info("worker.start", poll_sec=settings.worker_poll_interval_sec)

    while not _SHUTDOWN:
        now = datetime.now(timezone.utc)
        try:
            with SessionLocal() as db:
                beat(db, period_seconds=float(settings.worker_poll_interval_sec), note="idle")
                plan_job = claim_due_plan_job(db, now=now)
                if plan_job is not None:
                    run_plan_job(db, plan_job)
                    continue
                gen_job = claim_due_generation_job(db, now=now)
                if gen_job is not None:
                    run_generation_job(db, gen_job)
                    continue
                composition = claim_due_composition(db, now=now)
                if composition is not None:
                    run_composition(db, composition)
                    continue
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
