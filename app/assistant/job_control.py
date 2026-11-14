"""Background assistant runs that survive a browser reload."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthPrincipal
from app.db.models import AssistantJob
from app.logging_setup import get_logger

logger = get_logger(__name__)

STOPPED_TEXT = "выполнение остановлено"
RESTART_TEXT = "прервано перезапуском сервера"
_ACTIVE = ("running", "paused")
_LEFTOVER = ("running", "paused", "needs_user")
_lock = threading.Lock()
_threads: set[int] = set()


class JobStopped(Exception):
    pass


def actor_key(principal: AuthPrincipal) -> str:
    if principal.role == "operator" and principal.operator_id is not None:
        return f"operator:{principal.operator_id}"
    return "owner"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _open() -> Session:
    from app.db.session import SessionLocal

    return SessionLocal()


def fail_interrupted(db: Session | None = None) -> int:
    """Mark runs left behind by a dead process. Call once at API startup."""
    own = db is None
    session = db or _open()
    try:
        rows = session.scalars(
            select(AssistantJob).where(AssistantJob.status.in_(_LEFTOVER))
        ).all()
        changed = 0
        for row in rows:
            if row.id in _threads:
                continue
            row.status = "failed"
            row.error = RESTART_TEXT
            row.updated_at = _now()
            changed += 1
        if changed:
            session.commit()
        return changed
    finally:
        if own:
            session.close()


def active_job(db: Session, actor: str) -> AssistantJob | None:
    return db.scalar(
        select(AssistantJob)
        .where(AssistantJob.actor == actor, AssistantJob.status.in_(_ACTIVE))
        .order_by(AssistantJob.id.desc())
        .limit(1)
    )


def visible_job(db: Session, actor: str) -> AssistantJob | None:
    """Running work, or a finished run that is still waiting for the operator."""
    current = active_job(db, actor)
    if current is not None:
        return current
    return db.scalar(
        select(AssistantJob)
        .where(AssistantJob.actor == actor, AssistantJob.status == "needs_user")
        .order_by(AssistantJob.id.desc())
        .limit(1)
    )


def acknowledge(db: Session, job_id: int, actor: str) -> AssistantJob | None:
    row = get_owned(db, job_id, actor)
    if row is None or row.status != "needs_user":
        return None
    row.status = "done"
    row.updated_at = _now()
    db.commit()
    db.refresh(row)
    return row


def get_owned(db: Session, job_id: int, actor: str) -> AssistantJob | None:
    row = db.get(AssistantJob, job_id)
    if row is None or row.actor != actor:
        return None
    return row


def _touch(job_id: int, **fields: Any) -> None:
    db = _open()
    try:
        row = db.get(AssistantJob, job_id)
        if row is None:
            return
        for key, value in fields.items():
            setattr(row, key, value)
        row.updated_at = _now()
        db.commit()
    finally:
        db.close()


def read_status(job_id: int) -> str | None:
    db = _open()
    try:
        row = db.get(AssistantJob, job_id)
        return row.status if row is not None else None
    finally:
        db.close()


def checkpoint(job_id: int) -> None:
    """Block while the operator has taken over. Stop ends the run."""
    while True:
        status = read_status(job_id)
        if status in (None, "stopped"):
            raise JobStopped()
        if status == "paused":
            threading.Event().wait(0.25)
            continue
        return


def set_status(db: Session, job_id: int, actor: str, status: str) -> AssistantJob | None:
    row = get_owned(db, job_id, actor)
    if row is None:
        return None
    if status == "paused" and row.status != "running":
        return None
    if status == "running" and row.status != "paused":
        return None
    if status == "stopped" and row.status not in (*_ACTIVE, "needs_user"):
        return None
    row.status = status
    if status == "stopped":
        row.error = STOPPED_TEXT
    row.updated_at = _now()
    db.commit()
    db.refresh(row)
    return row


def _prompt_of(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user" and str(message.get("content") or "").strip():
            return str(message["content"]).strip()[:4000]
    return ""


def _result_payload(answer: Any) -> dict[str, Any]:
    opened = getattr(answer, "opened", None)
    return {
        "reply": answer.reply,
        "open_url": opened.as_url() if opened else None,
        "opened": opened.what if opened else None,
        "used": list(answer.used or []),
        "images": list(answer.images or []),
        "asks": list(answer.asks or []),
        "fields": list(answer.fields or []),
        "form_kind": answer.form_kind or "",
        "created": answer.created,
        "thinking": answer.thinking or "",
        "cut": answer.cut or "",
        "offer_local_switch": answer.offer_local_switch,
        "cards": list(answer.cards or []),
        "browser_target": answer.browser_target,
    }


def _consume(
    db: Session,
    job_id: int,
    messages: list[dict[str, Any]],
    settings: Any,
    token: str | None,
    page: str | None,
    account_id: int | None,
    focus_job_id: int | None,
    allow_browser: bool,
    viewer_role: str | None,
) -> Any:
    from app.assistant.chat import Answer, Step, stream

    answer = None
    for step in stream(
        db,
        messages,
        settings=settings,
        token=token,
        page=page,
        account_id=account_id,
        job_id=focus_job_id,
        allow_browser=allow_browser,
        viewer_role=viewer_role,
        control=lambda: checkpoint(job_id),
    ):
        if isinstance(step, Answer):
            answer = step
            _touch(job_id, reply=(step.reply or "")[:8000])
        elif isinstance(step, Step) and step.text:
            _touch(job_id, note=str(step.text)[:500], reply=_reply_progress(job_id, step))
    return answer


def _finish(job_id: int, messages: list[dict[str, Any]], answer: Any, token: str | None) -> None:
    from app.assistant.reports import notify_telegram, record_agent_report, report_screenshot_urls
    from app.config import get_settings

    settings = get_settings()
    asks = list(getattr(answer, "asks", None) or [])
    payload = _result_payload(answer)
    reply = (answer.reply or "").strip()
    if asks:
        text = reply or "Агенту нужно ваше действие."
        payload["reply"] = text
        _touch(
            job_id,
            status="needs_user",
            reply=text[:8000],
            error=None,
            note=text[:2000],
            result_json=json.dumps(payload, ensure_ascii=False),
        )
        report_db = _open()
        try:
            row = record_agent_report(
                report_db,
                source="panel",
                prompt=_prompt_of(messages),
                reply=text,
                error=None,
                images=list(answer.images or []),
                status="needs_user",
                settings=settings,
                token=token,
            )
            notify_telegram(text, report_screenshot_urls(row, settings), settings=settings)
        finally:
            report_db.close()
        return
    err = "; ".join(answer.tool_errors) if answer.tool_errors else None
    if err and err not in reply:
        reply = f"Ошибка: {err}\n\n{reply}".strip()
    payload["reply"] = reply
    _touch(
        job_id,
        status="failed" if err else "done",
        reply=reply[:8000],
        error=err,
        note="",
        result_json=json.dumps(payload, ensure_ascii=False),
    )
    report_db = _open()
    try:
        row = record_agent_report(
            report_db,
            source="panel",
            prompt=_prompt_of(messages),
            reply=reply,
            error=err,
            images=list(answer.images or []),
            status="failed" if err else "done",
            settings=settings,
            token=token,
        )
        notify_telegram(reply, report_screenshot_urls(row, settings), settings=settings)
    finally:
        report_db.close()


def _worker(
    job_id: int,
    messages: list[dict[str, Any]],
    *,
    token: str | None,
    page: str | None,
    account_id: int | None,
    focus_job_id: int | None,
    allow_browser: bool,
    viewer_role: str | None,
) -> None:
    from app.assistant.chat import AssistantError
    from app.assistant.run_log import bind
    from app.config import get_settings

    settings = get_settings()
    db = _open()
    try:
        with bind(job_id):
            answer = _consume(
                db,
                job_id,
                messages,
                settings,
                token,
                page,
                account_id,
                focus_job_id,
                allow_browser,
                viewer_role,
            )
        if answer is None:
            raise AssistantError("Ассистент не вернул ответ", retryable=True)
        _finish(job_id, messages, answer, token)
    except JobStopped:
        _touch(job_id, status="stopped", error=STOPPED_TEXT, note="")
        _store_stopped_report(job_id, token)
    except Exception as exc:
        logger.exception("assistant_job.failed")
        message = str(exc).strip() or "ошибка"
        _touch(job_id, status="failed", error=message[:2000], note="")
        _store_stopped_report(job_id, token, message)
    finally:
        db.close()
        with _lock:
            _threads.discard(job_id)


def _reply_progress(job_id: int, step: Any) -> str:
    if getattr(step, "kind", "") != "token":
        current = ""
        db = _open()
        try:
            row = db.get(AssistantJob, job_id)
            current = row.reply if row is not None else ""
        finally:
            db.close()
        return current
    db = _open()
    try:
        row = db.get(AssistantJob, job_id)
        base = row.reply if row is not None else ""
    finally:
        db.close()
    return (base + str(step.text))[:8000]


def _store_stopped_report(job_id: int, token: str | None, error: str | None = None) -> None:
    from app.assistant.reports import notify_telegram, record_agent_report, report_screenshot_urls
    from app.config import get_settings

    settings = get_settings()
    err = error or STOPPED_TEXT
    db = _open()
    try:
        row = db.get(AssistantJob, job_id)
        prompt = row.prompt if row is not None else ""
        reply = f"Ошибка: {err}"
        saved = record_agent_report(
            db,
            source="panel",
            prompt=prompt,
            reply=reply,
            error=err,
            images=[],
            status="failed",
            settings=settings,
            token=token,
        )
        notify_telegram(reply, report_screenshot_urls(saved, settings), settings=settings)
    except Exception:
        logger.exception("assistant_job.report_failed")
    finally:
        db.close()


def start_job(
    db: Session,
    actor: str,
    messages: list[dict[str, Any]],
    *,
    client_chat_id: str = "",
    token: str | None = None,
    page: str | None = None,
    account_id: int | None = None,
    focus_job_id: int | None = None,
    allow_browser: bool = False,
    viewer_role: str | None = None,
) -> tuple[AssistantJob, bool]:
    existing = active_job(db, actor)
    if existing is not None:
        return existing, False
    waiting = db.scalars(
        select(AssistantJob).where(AssistantJob.actor == actor, AssistantJob.status == "needs_user")
    ).all()
    for row in waiting:
        row.status = "done"
        row.updated_at = _now()
    if waiting:
        db.commit()
    row = AssistantJob(
        actor=actor,
        client_chat_id=(client_chat_id or "")[:80],
        prompt=_prompt_of(messages),
        status="running",
        reply="",
        note="",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    with _lock:
        _threads.add(row.id)
    thread = threading.Thread(
        target=_worker,
        kwargs={
            "job_id": row.id,
            "messages": messages,
            "token": token,
            "page": page,
            "account_id": account_id,
            "focus_job_id": focus_job_id,
            "allow_browser": allow_browser,
            "viewer_role": viewer_role,
        },
        daemon=True,
        name=f"assistant-job-{row.id}",
    )
    thread.start()
    return row, True
