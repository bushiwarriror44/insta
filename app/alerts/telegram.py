"""Telegram alerting via the Bot HTTP API.

We avoid pulling a heavy aiogram dependency for this — a single httpx call
is enough. Failures to deliver alerts are logged but never raised.
"""
from __future__ import annotations

from typing import Optional

import httpx

from app.config import settings
from app.db import Event, EventLevel, SessionLocal
from app.logging_setup import get_logger

logger = get_logger(__name__)


def _enabled() -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


def send(text: str, *, level: EventLevel = EventLevel.info, account_id: Optional[int] = None, kind: str = "alert") -> None:
    """Send a Telegram message and persist an Event row regardless of delivery."""
    _persist_event(text=text, level=level, account_id=account_id, kind=kind)

    if not _enabled():
        logger.debug("telegram.disabled")
        return

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    icon = {"info": "ℹ️", "warn": "⚠️", "error": "❌", "critical": "🚨"}.get(level.value, "•")
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": f"{icon} [{level.value.upper()}] {text}",
        "disable_web_page_preview": True,
    }
    try:
        with httpx.Client(timeout=10) as client:
            response = client.post(url, json=payload)
            if response.status_code >= 300:
                logger.warning("telegram.send_failed", status=response.status_code, body=response.text[:300])
    except httpx.HTTPError as exc:
        logger.warning("telegram.exception", error=str(exc))


def _persist_event(*, text: str, level: EventLevel, account_id: Optional[int], kind: str) -> None:
    try:
        with SessionLocal() as session:
            session.add(Event(account_id=account_id, level=level, kind=kind, message=text))
            session.commit()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("event.persist_failed", error=str(exc))


def notify_challenge(username: str, choice: object, account_id: Optional[int]) -> None:
    send(
        f"Challenge for @{username} ({choice}). Drop the code into "
        f"data/challenges/{username}.code",
        level=EventLevel.warn,
        account_id=account_id,
        kind="challenge",
    )


def notify_blocked(username: str, account_id: Optional[int], reason: str) -> None:
    send(
        f"Account @{username} marked BLOCKED. Reason: {reason}",
        level=EventLevel.critical,
        account_id=account_id,
        kind="blocked",
    )


def notify_proxy_down(label: str, error: str) -> None:
    send(
        f"Proxy `{label}` failed health-check: {error}",
        level=EventLevel.error,
        kind="proxy_down",
    )


def notify_publish_failure(username: str, account_id: Optional[int], error: str, attempt: int) -> None:
    send(
        f"Publish failed for @{username} (attempt {attempt}): {error}",
        level=EventLevel.warn,
        account_id=account_id,
        kind="publish_failed",
    )
