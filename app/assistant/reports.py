"""Persist autonomous agent tasks and their screenshots."""
from __future__ import annotations

import json
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant.browser_shots import evidence_url, filename_of
from app.config import Settings, get_settings
from app.db.models import AgentReport
from app.logging_setup import get_logger
from app.services.media import MediaError, resolve
from app.services.panel_browser import signed_url

logger = get_logger(__name__)


def _filenames(images: list[str]) -> list[str]:
    names: list[str] = []
    for image in images:
        name = filename_of(image)
        if name and name not in names:
            names.append(name)
    return names


def record_agent_report(
    db: Session,
    *,
    source: str,
    prompt: str,
    reply: str = "",
    error: str | None = None,
    images: list[str] | None = None,
    status: str | None = None,
    settings: Settings | None = None,
    token: str | None = None,
) -> AgentReport:
    settings = settings or get_settings()
    shots = list(images or [])
    err = (error or "").strip() or None
    final_status = status or ("failed" if err else "done")
    if final_status == "failed" and not _filenames(shots):
        url = evidence_url(
            db,
            error=err or reply or "Задача не выполнена",
            settings=settings,
            token=token,
            allow_panel=True,
        )
        if url:
            shots.append(url)
    row = AgentReport(
        source=(source or "panel")[:16],
        status=final_status[:16],
        prompt=(prompt or "")[:4000],
        reply=(reply or "")[:8000],
        error=err[:4000] if err else None,
        screenshots_json=json.dumps(_filenames(shots)),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def report_screenshot_urls(row: AgentReport, settings: Settings | None = None) -> list[str]:
    settings = settings or get_settings()
    urls: list[str] = []
    for name in row.screenshots:
        if not isinstance(name, str) or not name:
            continue
        try:
            resolve(settings.screenshots_dir, name)
        except MediaError:
            continue
        path = settings.screenshots_dir / name
        if path.is_file():
            urls.append(signed_url(name, settings))
    return urls


def delete_agent_report(db: Session, report_id: int, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    row = db.get(AgentReport, report_id)
    if row is None:
        return False
    for name in list(row.screenshots):
        if not isinstance(name, str):
            continue
        try:
            resolved = resolve(settings.screenshots_dir, name)
        except MediaError:
            continue
        resolved.unlink(missing_ok=True)
    db.delete(row)
    db.commit()
    return True


def list_agent_reports(db: Session, *, limit: int = 100) -> list[AgentReport]:
    stmt = select(AgentReport).order_by(AgentReport.created_at.desc(), AgentReport.id.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def notify_telegram(
    text: str,
    images: list[str],
    *,
    settings: Settings | None = None,
    chat_id: str | int | None = None,
) -> None:
    """Send the same report text and screenshots to the operator bot chat."""
    settings = settings or get_settings()
    from app.telegram import api_client

    token = api_client.agent_bot_token(settings)
    target = str(chat_id or settings.telegram_chat_id or "").strip()
    if not token or not target:
        return
    try:
        chat = int(target)
    except ValueError:
        logger.warning("agent_report.bad_chat_id")
        return
    body = (text or "").strip() or "Готово"
    try:
        api_client.send_message(token, chat, body[:4000])
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_report.telegram_text_failed", error=str(exc))
        return
    for name in _filenames(images):
        path = settings.screenshots_dir / name
        if not path.is_file():
            continue
        try:
            api_client.send_photo(token, chat, path, caption=body[:900])
        except Exception as exc:  # noqa: BLE001
            logger.warning("agent_report.telegram_photo_failed", error=str(exc))
