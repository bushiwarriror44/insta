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
import re
import signal
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.operator_text import operator_error
from app.accounts.session_manager import (
    ensure_fingerprint_and_proxy,
    maybe_rotate_session_uuids,
)
from app.accounts.status import status_label
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
    TemporaryPublishError,
    publish_feed_photo,
    publish_feed_video,
    publish_reel,
)
from app.publisher.tiktok_publisher import publish_tiktok
from app.publisher.youtube_publisher import publish_youtube_short
from app.db.models import Composition, GenerationJob, PipelineStatus, PlanJob, Platform
from app.scheduler.queue import reclaim_stale_running
from app.services.composing import claim_due_composition, run_composition
from app.services.generation import claim_due_generation_job, run_generation_job
from app.services.planning import claim_due_plan_job, run_plan_job
from app.publications.stats import sync_recent_publication_stats
from app.scheduler.heartbeat import beat
from app.scheduler.planner import (
    CROSS_ACCOUNT_SPREAD_MINUTES,
    can_post_today,
    increment_daily_stat,
)
from app.risk.profiles import classify_account_risk, profile_min_gap_for_account, quarantine_retry_delay
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

    Skips jobs whose account is paused, challenge, blocked, or still inside an
    anti-detection cooldown. Expired-cooldown accounts stay eligible so
    ``_process_job`` can restore them to active. Challenge/blocked rows stay
    ``queued`` until the operator clears the account — they must not burn
    attempts on hourly claim/requeue cycles.
    """
    base_filters = (
        (PostJob.status == PostJobStatus.queued),
        (PostJob.scheduled_for <= now),
    )
    cooldown_filter = (
        (Account.cooldown_until.is_(None)) | (Account.cooldown_until <= now)
    )
    # Only active accounts, or cooldown whose window has already expired
    # (process restores status to active). Challenge/blocked must not be
    # claimed — that burned attempts every hour while the account was stuck.
    status_filter = (
        (Account.status == AccountStatus.active)
        | (Account.status == AccountStatus.cooldown)
    )

    stmt = (
        select(PostJob)
        .join(Account, Account.id == PostJob.account_id)
        .where(*base_filters, cooldown_filter, status_filter)
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
            .where(*base_filters, cooldown_filter, status_filter)
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


def _another_account_just_posted(db: Session, account_id: int) -> bool:
    """True when some other account posted or is posting inside the spread window."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=CROSS_ACCOUNT_SPREAD_MINUTES)
    recent = db.scalar(
        select(PostJob.id).where(
            PostJob.account_id != account_id,
            PostJob.status == PostJobStatus.done,
            PostJob.finished_at >= since,
        )
    )
    if recent is not None:
        return True
    inflight = db.scalar(
        select(PostJob.id).where(
            PostJob.account_id != account_id,
            PostJob.status == PostJobStatus.running,
        )
    )
    return inflight is not None


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
    # Soft deferrals (hours / cap / gap / spread / inactive) must not burn
    # ``attempts`` — only a real publish attempt counts toward dead-letter.

    diag = DiagnosticCollector(
        db,
        kind=DiagnosticRunKind.publish_job,
        account_id=job.account_id,
        job_id=job.id,
    )
    on_log = diag.callback()

    def _done(status: str, summary: str) -> None:
        diag.finish(status, summary)  # type: ignore[arg-type]

    diag.info("start", f"Задача #{job.id}, попыток уже {job.attempts}")

    account = db.get(Account, job.account_id)
    if account is None:
        job.status = PostJobStatus.dead
        job.last_error = "аккаунт не найден"
        db.commit()
        diag.error("account", "Запись аккаунта отсутствует")
        _done("fail", "аккаунт не найден")
        return

    log = log.bind(username=account.username)
    risk_profile = classify_account_risk(account)
    log = log.bind(risk_profile=risk_profile.name)
    diag.info("account", f"@{account.username} статус={status_label(account.status.value)}")

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
            diag.info("account", "Пауза IG истекла — статус активен")

    if account.status != AccountStatus.active:
        job.status = PostJobStatus.queued
        job.last_error = f"статус аккаунта: {status_label(account.status.value)}"
        job.scheduled_for = _clamp_to_active_window(
            account, datetime.now(timezone.utc) + timedelta(hours=1)
        )
        db.commit()
        log.warning("worker.account_not_active", status=account.status.value)
        diag.warn("account", f"Аккаунт неактивен: {status_label(account.status.value)}")
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
        _done("warn", "вне часов активности")
        return

    if not can_post_today(db, account):
        job.status = PostJobStatus.queued
        local_now = datetime.now(timezone.utc).astimezone(_account_tz(account))
        start_h = max(0, min(23, account.active_hour_start))
        next_open = (local_now + timedelta(days=1)).replace(
            hour=start_h, minute=0, second=0, microsecond=0
        )
        job.scheduled_for = next_open.astimezone(timezone.utc)
        db.commit()
        log.info("worker.daily_cap_reached_reschedule")
        diag.info("cap", "Дневной лимит публикаций — перенос на следующее окно")
        _done("warn", "дневной лимит публикаций")
        return

    last_publish = account.last_publish_at
    gap_hours = profile_min_gap_for_account(account)
    if last_publish is not None and gap_hours > 0:
        if last_publish.tzinfo is None:
            last_publish = last_publish.replace(tzinfo=timezone.utc)
        earliest = last_publish + timedelta(hours=float(gap_hours))
        if earliest > datetime.now(timezone.utc):
            job.status = PostJobStatus.queued
            job.scheduled_for = _clamp_to_active_window(account, earliest)
            job.last_error = "интервал между публикациями"
            db.commit()
            log.info("worker.min_gap_reschedule")
            diag.info("gap", "Между публикациями ещё не прошёл интервал — перенос")
            _done("warn", "интервал между публикациями")
            return

    if _another_account_just_posted(db, account.id):
        job.status = PostJobStatus.queued
        job.scheduled_for = _clamp_to_active_window(
            account,
            datetime.now(timezone.utc) + timedelta(minutes=CROSS_ACCOUNT_SPREAD_MINUTES),
        )
        job.last_error = "разнесение между аккаунтами"
        db.commit()
        log.info("worker.cross_account_spread")
        diag.info("spread", "Другой аккаунт только что публиковал — перенос на 2 мин")
        _done("warn", "разнесение между аккаунтами")
        return

    job.attempts += 1
    diag.info("attempt", f"Реальная попытка публикации #{job.attempts}")

    proxy = _account_proxy(db, account)
    if proxy is None:
        diag.error("proxy", "Прокси не назначен")
        _done("fail", "прокси не назначен")
        _fail_hard(db, job, account, "прокси не назначен")
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
        _done("fail", f"прокси недоступен: {exc}")
        _fail_temporary(db, job, account, f"прокси недоступен: {exc}")
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
                    message=f"Прокси {proxy.label} риск={risk:.2f}",
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
        _done("fail", f"исходный файл отсутствует: {src}")
        _fail_hard(db, job, account, f"исходный файл отсутствует: {src}")
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
            _done("fail", f"uniquify не удался: {exc}")
            _fail_temporary(db, job, account, f"uniquify не удался: {exc}")
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
        if platform == Platform.youtube:
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
        elif platform == Platform.tiktok:
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
        elif post_type == PostType.feed_photo.value:
            result = publish_feed_photo(image_path=out_path, **common)
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
        shown = operator_error(exc)
        diag.warn("publish", f"Пауза действий {cooldown_hours} ч: {shown}")
        db.add(
            Event(
                account_id=account.id,
                level=EventLevel.warn,
                kind="account_cooldown",
                message=(
                    f"пауза действий {cooldown_hours}ч после запроса обратной связи: {shown}"
                ),
            )
        )
        _record_post_log(
            db, job, account, success=False, error=shown,
            final_video=out_path, final_caption=caption,
        )
        increment_daily_stat(db, account, success=False)
        # Re-queue the job after cooldown so it isn't lost.
        job.status = PostJobStatus.queued
        job.last_error = f"пауза: {shown}"
        job.next_attempt_at = cooldown_until + timedelta(minutes=random.randint(5, 25))
        job.scheduled_for = job.next_attempt_at
        db.commit()
        _done("warn", f"пауза: {shown}")
        return
    except HardPublishError as exc:
        shown_hard = operator_error(exc)
        log.error("worker.hard_publish_error", error=str(exc))
        diag.error("publish", shown_hard)
        account.status = AccountStatus.blocked
        notify_blocked(account.username, account.id, shown_hard)
        _record_post_log(db, job, account, success=False, error=shown_hard, final_video=out_path, final_caption=caption)
        increment_daily_stat(db, account, success=False)
        job.status = PostJobStatus.dead
        job.last_error = shown_hard
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        _done("fail", shown_hard)
        return
    except TemporaryPublishError as exc:
        shown_temp = operator_error(exc)
        log.warning("worker.temp_publish_error", error=str(exc), attempt=job.attempts)
        diag.warn("publish", shown_temp)
        notify_publish_failure(account.username, account.id, shown_temp, job.attempts)
        _record_post_log(db, job, account, success=False, error=shown_temp, final_video=out_path, final_caption=caption)
        increment_daily_stat(db, account, success=False)
        if _should_quarantine(account, str(exc), job.attempts):
            _enter_quarantine(db, job, account, reason=shown_temp)
            _done("warn", f"карантин: {shown_temp}")
            return
        _fail_temporary(db, job, account, shown_temp)
        _done("warn", shown_temp)
        return
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("worker.unexpected")
        diag.error("publish", f"неожиданная ошибка: {exc}")
        _fail_temporary(db, job, account, f"неожиданная ошибка: {exc}")
        _done("fail", f"неожиданная ошибка: {exc}")
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
    _done("ok", f"Опубликовано media_id={result.media_id}")


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
                message=(
                    f"задача {job.id} в мёртвых после {job.attempts} попыток: {message}"
                ),
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
    auth_hit = any(h in msg for h in auth_hints) and attempts >= 2
    status_hit = account.status in (AccountStatus.challenge, AccountStatus.cooldown)
    enter = auth_hit or status_hit
    return enter


def _enter_quarantine(db: Session, job: PostJob, account: Account, *, reason: str) -> None:
    until = quarantine_retry_delay(account)
    account.status = AccountStatus.cooldown
    account.cooldown_until = until
    job.status = PostJobStatus.queued
    job.last_error = f"карантин: {reason}"
    job.next_attempt_at = until
    job.scheduled_for = until
    db.add(
        Event(
            account_id=account.id,
            level=EventLevel.warn,
            kind="risk.quarantine",
            message=(
                f"Аккаунт в карантине до {until.isoformat()} ({reason})"
            ),
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
            message=f"задача {job.id} жёсткий сбой: {message}",
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


def _redact_proxy(text: str) -> str:
    return re.sub(r"URL\('[^']*'\)", "URL('…')", text)


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
                stale_after = now - timedelta(
                    seconds=max(float(settings.generation_timeout_seconds) * 2, 1800)
                )
                post_after = now - timedelta(minutes=30)
                for model in (GenerationJob, Composition, PlanJob):
                    reclaim_stale_running(
                        db,
                        model,
                        running=PipelineStatus.running,
                        queued=PipelineStatus.queued,
                        older_than=stale_after,
                        now=now,
                    )
                reclaim_stale_running(
                    db,
                    PostJob,
                    running=PostJobStatus.running,
                    queued=PostJobStatus.queued,
                    older_than=post_after,
                    now=now,
                )
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
                        logger.warning("worker.idle_warmup_failed", error=_redact_proxy(str(exc)))
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("worker.loop_error", error=str(exc))

        sleep_for = jitter_seconds(settings.worker_poll_interval_sec, spread=0.3)
        end = time.monotonic() + sleep_for
        while time.monotonic() < end:
            if _SHUTDOWN:
                break
            time.sleep(0.5)

    logger.info("worker.stopped")
