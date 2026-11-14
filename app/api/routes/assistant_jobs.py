"""Start, pause, and stop a background assistant run."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, AuthPrincipal, get_db
from app.api.routes.assistant import AssistantMessage, _bearer
from app.assistant.job_control import (
    acknowledge,
    actor_key,
    get_owned,
    set_status,
    start_job,
    visible_job,
)
from app.db.models import AssistantJob

router = APIRouter(prefix="/api/assistant/jobs", tags=["assistant-jobs"], dependencies=[AuthDep])


class AssistantJobIn(BaseModel):
    messages: list[AssistantMessage]
    page: Optional[str] = None
    account_id: Optional[int] = None
    job_id: Optional[int] = None
    allow_browser: bool = False
    client_chat_id: str = ""


class AssistantJobOut(BaseModel):
    id: int
    status: str
    actor: str
    client_chat_id: str
    prompt: str
    reply: str
    error: Optional[str] = None
    note: str = ""
    result: Optional[dict[str, Any]] = None
    created_at: datetime
    fresh: bool = True


def _out(row: AssistantJob, *, fresh: bool = True) -> AssistantJobOut:
    result = None
    if row.result_json:
        try:
            parsed = json.loads(row.result_json)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            result = parsed
    return AssistantJobOut(
        id=row.id,
        status=row.status,
        actor=row.actor,
        client_chat_id=row.client_chat_id,
        prompt=row.prompt,
        reply=row.reply,
        error=row.error,
        note=row.note,
        result=result,
        created_at=row.created_at,
        fresh=fresh,
    )


@router.get("/active", response_model=Optional[AssistantJobOut])
def current_job(
    db: Session = Depends(get_db),
    principal: AuthPrincipal = AuthDep,
) -> Optional[AssistantJobOut]:
    row = visible_job(db, actor_key(principal))
    if row is None:
        return None
    return _out(row)


@router.get("/{job_id}", response_model=AssistantJobOut)
def read_job(
    job_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = AuthDep,
) -> AssistantJobOut:
    row = get_owned(db, job_id, actor_key(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="задача не найдена")
    return _out(row)


@router.post("", response_model=AssistantJobOut)
def create_job(
    payload: AssistantJobIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = AuthDep,
    authorization: Optional[str] = Header(default=None),
) -> AssistantJobOut:
    if not any(
        message.role == "user" and (message.content.strip() or message.attachments)
        for message in payload.messages
    ):
        raise HTTPException(status_code=400, detail="Нужно непустое сообщение пользователя")
    allow_browser = bool(payload.allow_browser and principal.role == "owner")
    row, fresh = start_job(
        db,
        actor_key(principal),
        [message.model_dump(mode="json") for message in payload.messages],
        client_chat_id=payload.client_chat_id,
        token=_bearer(authorization),
        page=payload.page,
        account_id=payload.account_id,
        focus_job_id=payload.job_id,
        allow_browser=allow_browser,
        viewer_role=principal.role,
    )
    if not fresh:
        raise HTTPException(status_code=409, detail="агент уже выполняет задачу")
    return _out(row, fresh=fresh)


@router.post("/{job_id}/pause", response_model=AssistantJobOut)
def pause_job(
    job_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = AuthDep,
) -> AssistantJobOut:
    row = set_status(db, job_id, actor_key(principal), "paused")
    if row is None:
        raise HTTPException(status_code=404, detail="задачу нельзя поставить на паузу")
    return _out(row)


@router.post("/{job_id}/resume", response_model=AssistantJobOut)
def resume_job(
    job_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = AuthDep,
) -> AssistantJobOut:
    row = set_status(db, job_id, actor_key(principal), "running")
    if row is None:
        raise HTTPException(status_code=404, detail="задачу нельзя продолжить")
    return _out(row)


@router.post("/{job_id}/ack", response_model=AssistantJobOut)
def ack_job(
    job_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = AuthDep,
) -> AssistantJobOut:
    row = acknowledge(db, job_id, actor_key(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="окно уже закрыто")
    return _out(row)


@router.post("/{job_id}/stop", response_model=AssistantJobOut)
def stop_job(
    job_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = AuthDep,
) -> AssistantJobOut:
    row = set_status(db, job_id, actor_key(principal), "stopped")
    if row is None:
        raise HTTPException(status_code=404, detail="задачу нельзя остановить")
    return _out(row)
