"""Best-effort statistics refresh for already published media."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.accounts.session_manager import ensure_fingerprint_and_proxy
from app.db import Account, PostLog, Proxy
from app.geo.timezone_normalize import timezone_from_proxy
from app.logging_setup import get_logger
from app.publisher.reels_publisher import MediaStats, fetch_media_stats

logger = get_logger(__name__)

STATS_REFRESH_MIN_AGE = timedelta(minutes=30)
STATS_SYNC_LOOKBACK = timedelta(days=14)


def apply_stats(post_log: PostLog, stats: MediaStats, *, now: datetime | None = None) -> None:
    """Copy normalized stat counters into a ``PostLog`` row.

    Only non-``None`` counters overwrite existing values so a partial Instagram
    payload cannot wipe previously stored metrics.
    """
    if stats.view_count is not None:
        post_log.view_count = stats.view_count
    if stats.like_count is not None:
        post_log.like_count = stats.like_count
    if stats.comment_count is not None:
        post_log.comment_count = stats.comment_count
    if stats.play_count is not None:
        post_log.play_count = stats.play_count
    if stats.save_count is not None:
        post_log.save_count = stats.save_count
    if stats.share_count is not None:
        post_log.share_count = stats.share_count
    post_log.raw_stats_json = stats.raw_json
    post_log.last_stats_at = now or datetime.now(timezone.utc)



def refresh_post_log_stats(db: Session, post_log: PostLog) -> PostLog:
    """Refresh counters for one successful publication."""
    if not post_log.success:
        raise ValueError("нельзя обновить статистику для неудачной публикации")
    if not post_log.media_id:
        raise ValueError("у публикации нет media_id")

    account = db.get(Account, post_log.account_id)
    if account is None:
        raise ValueError("аккаунт публикации не найден")
    proxy = db.get(Proxy, account.proxy_id) if account.proxy_id is not None else None
    if proxy is None:
        raise ValueError("у аккаунта публикации нет прокси")

    fingerprint = ensure_fingerprint_and_proxy(
        account.username,
        country=proxy.country or "US",
        timezone_id=timezone_from_proxy(proxy.timezone, proxy.country),
    )
    stats = fetch_media_stats(
        username=account.username,
        password=account.password,
        fingerprint=fingerprint,
        proxy_url=proxy.url,
        media_id=post_log.media_id,
        totp_seed=account.totp_seed,
        session_id=account.session_id,
        email=account.email,
        email_password=account.email_password,
    )
    apply_stats(post_log, stats)
    db.commit()
    db.refresh(post_log)
    return post_log


def sync_recent_publication_stats(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int = 5,
) -> int:
    """Refresh a small batch of recent publications that are stale enough."""
    now = now or datetime.now(timezone.utc)
    stale_before = now - STATS_REFRESH_MIN_AGE
    since = now - STATS_SYNC_LOOKBACK
    stmt = (
        select(PostLog)
        .where(
            PostLog.success.is_(True),
            PostLog.media_id.isnot(None),
            PostLog.created_at >= since,
            or_(PostLog.last_stats_at.is_(None), PostLog.last_stats_at <= stale_before),
        )
        .order_by(PostLog.last_stats_at.asc(), PostLog.created_at.desc())
        .limit(limit)
    )
    refreshed = 0
    for post_log in db.scalars(stmt).all():
        try:
            refresh_post_log_stats(db, post_log)
            refreshed += 1
        except Exception as exc:  # noqa: BLE001 - stats sync must not stop posting
            db.rollback()
            logger.warning("publication.stats_sync_failed", post_log_id=post_log.id, error=str(exc))
    return refreshed
