"""The prompt box on the dashboard."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_db
from app.assistant.chat import Answer, AssistantError, Step, ask, stream
from app.config import Settings, get_settings

router = APIRouter(prefix="/api/assistant", tags=["assistant"], dependencies=[AuthDep])


class AssistantMessage(BaseModel):
    role: str
    content: str


class AssistantIn(BaseModel):
    messages: list[AssistantMessage]
    page: Optional[str] = None
    account_id: Optional[int] = None
    job_id: Optional[int] = None


class AssistantRunIn(BaseModel):
    prompt: str = Field(min_length=1)
    page: Optional[str] = None
    account_id: Optional[int] = None
    job_id: Optional[int] = None


class AssistantOut(BaseModel):
    reply: str
    open_url: Optional[str] = None
    opened: Optional[str] = None
    used: list[str] = []
    images: list[str] = []
    asks: list[str] = []
    created: dict[str, list[int]] = Field(default_factory=lambda: {"accounts": [], "proxies": []})


def _bearer(authorization: Optional[str]) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return authorization.split(" ", 1)[1].strip() or None


@router.post("", response_model=AssistantOut)
def talk(
    payload: AssistantIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    authorization: Optional[str] = Header(default=None),
) -> AssistantOut:
    try:
        answer = ask(
            db,
            [m.model_dump() for m in payload.messages],
            settings=settings,
            token=_bearer(authorization),
            page=payload.page,
            account_id=payload.account_id,
            job_id=payload.job_id,
        )
    except AssistantError as exc:
        raise HTTPException(status_code=503 if exc.retryable else 409, detail=str(exc)) from exc
    return _answer_out(answer)


def _answer_out(answer: Answer) -> AssistantOut:
    return AssistantOut(
        reply=answer.reply,
        open_url=answer.opened.as_url() if answer.opened else None,
        opened=answer.opened.what if answer.opened else None,
        used=answer.used,
        images=answer.images,
        asks=answer.asks,
        created=answer.created,
    )


@router.post("/run", response_model=AssistantOut)
def run_prompt(
    payload: AssistantRunIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    authorization: Optional[str] = Header(default=None),
) -> AssistantOut:
    try:
        answer = ask(
            db,
            [{"role": "user", "content": payload.prompt}],
            settings=settings,
            token=_bearer(authorization),
            page=payload.page,
            account_id=payload.account_id,
            job_id=payload.job_id,
            allow_browser=True,
        )
    except AssistantError as exc:
        raise HTTPException(status_code=503 if exc.retryable else 409, detail=str(exc)) from exc
    return _answer_out(answer)


@router.post("/stream")
def talk_streaming(
    payload: AssistantIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    authorization: Optional[str] = Header(default=None),
) -> StreamingResponse:
    token = _bearer(authorization)

    def events() -> Iterator[str]:
        try:
            for step in stream(
                db,
                [m.model_dump() for m in payload.messages],
                settings=settings,
                token=token,
                page=payload.page,
                account_id=payload.account_id,
                job_id=payload.job_id,
            ):
                if isinstance(step, Answer):
                    yield _event(
                        {
                            "type": "done",
                            "reply": step.reply,
                            "open_url": step.opened.as_url() if step.opened else None,
                            "opened": step.opened.what if step.opened else None,
                            "used": step.used,
                            "images": step.images,
                            "asks": step.asks,
                            "created": step.created,
                        }
                    )
                elif isinstance(step, Step):
                    payload_step: dict = {"type": step.kind, "text": step.text}
                    if step.questions:
                        payload_step["questions"] = step.questions
                    yield _event(payload_step)
        except AssistantError as exc:
            yield _event({"type": "error", "detail": str(exc), "retryable": exc.retryable})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


def _event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
