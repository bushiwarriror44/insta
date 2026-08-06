"""Idle warmup loop.

Beyond the warmup that immediately precedes a publish, real users open the
app even on days they don't post. To avoid the "active only when uploading"
fingerprint we periodically run a *publish-less* warmup for a randomly chosen
account that hasn't been touched in a while.

The function is intentionally dependency-light: it accepts the username +
pre-built fingerprint + proxy + (optional) totp_seed and reuses the standard
``login_or_resume`` path. The worker chooses *when* to run it; this module
only knows *how*.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.session_manager import (
    AuthenticationError,
    HardCheckpoint,
    ensure_fingerprint_and_proxy,
    login_or_resume,
)
from app.accounts.challenge import make_handler
from app.behavior.humanizer import think
from app.behavior.warmup_instagrapi import warmup
from app.geo.timezone_normalize import timezone_from_proxy
from app.db import Account, AccountStatus, Event, EventLevel, Proxy
from app.logging_setup import get_logger
from app.proxies.pool import HealthCheckScope, ProxyError, health_check_cached

logger = get_logger(__name__)


# Probability the worker tick triggers an idle warmup attempt.
IDLE_TICK_PROBABILITY = 0.05
# Minimum idle time (since last publish AND since last idle warmup) before
# an account becomes eligible.
MIN_IDLE_HOURS = 6
MAX_IDLE_HOURS = 12


def _pick_idle_account(db: Session) -> Optional[Account]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=MIN_IDLE_HOURS)

    stmt = (
        select(Account)
        .where(Account.status == AccountStatus.active)
        .where(
            (Account.cooldown_until.is_(None)) | (Account.cooldown_until <= now)
        )
        .where(
            (Account.last_idle_warmup_at.is_(None))
            | (Account.last_idle_warmup_at <= cutoff)
        )
    )
    candidates = list(db.scalars(stmt))
    if not candidates:
        return None
    return random.choice(candidates)


def _proxy_for(db: Session, account: Account) -> Optional[Proxy]:
    if account.proxy_id is None:
        return None
    return db.get(Proxy, account.proxy_id)


def idle_warmup(username: str) -> bool:
    """Run a publish-less warmup pass for a single account.

    Returns ``True`` on success, ``False`` if the warmup was skipped or the
    session/proxy were unavailable. Never raises.
    """
    log = logger.bind(username=username, kind="idle_warmup")

    from app.db import SessionLocal  # local import to break cycle for tests

    with SessionLocal() as db:
        account = db.scalar(select(Account).where(Account.username == username))
        if account is None:
            log.warning("idle.account_missing")
            return False
        if account.status != AccountStatus.active:
            log.info("idle.account_not_active", status=account.status.value)
            return False
        proxy = _proxy_for(db, account)
        if proxy is None:
            log.info("idle.no_proxy")
            return False
        proxy_url = proxy.url
        proxy_country = proxy.country or "US"
        proxy_timezone_id = timezone_from_proxy(proxy.timezone, proxy.country)
        totp_seed = account.totp_seed
        session_id = account.session_id
        password = account.password
        email = account.email
        email_password = account.email_password
        account_id = account.id

    try:
        health_check_cached(proxy_url, scope=HealthCheckScope.MINIMAL)
    except ProxyError as exc:
        log.warning("idle.proxy_unhealthy", error=str(exc))
        return False

    fingerprint = ensure_fingerprint_and_proxy(
        username, country=proxy_country, timezone_id=proxy_timezone_id
    )
    handler = make_handler(username, email=email, email_password=email_password)

    try:
        client = login_or_resume(
            username=username,
            password=password,
            fingerprint=fingerprint,
            proxy_url=proxy_url,
            challenge_handler=handler,
            totp_seed=totp_seed,
            session_id=session_id,
        )
    except (HardCheckpoint, AuthenticationError) as exc:
        log.warning("idle.auth_failed", error=str(exc))
        return False
    except Exception as exc:  # noqa: BLE001 - never escalate from idle path
        log.warning("idle.auth_unexpected", error=str(exc))
        return False

    intensity = random.choice(["light", "normal", "normal", "heavy"])
    try:
        warmup(client, intensity=intensity)
    except Exception as exc:  # noqa: BLE001 - warmup is best effort
        log.warning("idle.warmup_failed", error=str(exc))
        return False

    # Tail "browse some more" pause to break login → warmup → logout pattern.
    think(median_sec=8.0, max_sec=25.0)

    with SessionLocal() as db:
        account = db.get(Account, account_id)
        if account is not None:
            account.last_idle_warmup_at = datetime.now(timezone.utc)
            db.add(
                Event(
                    account_id=account_id,
                    level=EventLevel.info,
                    kind="idle_warmup",
                    message=f"idle warmup ok (intensity={intensity})",
                )
            )
            db.commit()

    log.info("idle.done", intensity=intensity)
    return True


def maybe_run_idle_warmup(probability: float = IDLE_TICK_PROBABILITY) -> bool:
    """Worker-tick hook: with given probability, pick an idle account and warm it."""
    if random.random() >= probability:
        return False

    from app.db import SessionLocal  # local import

    with SessionLocal() as db:
        candidate = _pick_idle_account(db)
        if candidate is None:
            return False
        username = candidate.username

    return idle_warmup(username)
