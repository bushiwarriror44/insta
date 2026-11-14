"""Saved agent tasks and their screenshots."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, AuthPrincipal, get_db
from app.assistant.job_control import actor_key
from app.assistant.reports import delete_agent_report, list_agent_reports, report_screenshot_urls
from app.assistant.run_log import format_logs
from app.config import Settings, get_settings
from app.db.models import AgentReport, AgentRunLog, AssistantJob

router = APIRouter(prefix="/api/agent-reports", tags=["agent-reports"], dependencies=[AuthDep])


class AgentReportOut(BaseModel):
    id: int
    source: str
    status: str
    prompt: str
    reply: str
    error: str | None
    screenshots: list[str]
    created_at: datetime


def _out(row: AgentReport, settings: Settings) -> AgentReportOut:
    return AgentReportOut(
        id=row.id,
        source=row.source,
        status=row.status,
        prompt=row.prompt,
        reply=row.reply,
        error=row.error,
        screenshots=report_screenshot_urls(row, settings),
        created_at=row.created_at,
    )


@router.get(
    "",
    response_model=list[AgentReportOut],
    summary="Список отчётов",
    description="Сохранённые задачи агента и ссылки на снимки экрана.",
)
def list_reports(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[AgentReportOut]:
    return [_out(row, settings) for row in list_agent_reports(db, limit=limit)]


class AgentRunLogGroup(BaseModel):
    job_id: int
    prompt: str
    status: str
    created_at: datetime
    text: str


@router.get(
    "/logs",
    response_model=list[AgentRunLogGroup],
    summary="Журнал прогонов",
    description="Строки действий текущего входа. Чужой прогон не возвращается.",
)
def list_run_logs(
    db: Session = Depends(get_db),
    principal: AuthPrincipal = AuthDep,
) -> list[AgentRunLogGroup]:
    actor = actor_key(principal)
    jobs = db.scalars(
        select(AssistantJob)
        .where(AssistantJob.actor == actor)
        .order_by(AssistantJob.id.desc())
        .limit(50)
    ).all()
    groups: list[AgentRunLogGroup] = []
    for job in jobs:
        rows = db.scalars(
            select(AgentRunLog)
            .where(AgentRunLog.assistant_job_id == job.id)
            .order_by(AgentRunLog.id.asc())
        ).all()
        if not rows:
            continue
        groups.append(
            AgentRunLogGroup(
                job_id=job.id,
                prompt=job.prompt,
                status=job.status,
                created_at=job.created_at,
                text=format_logs(rows),
            )
        )
    return groups


@router.delete(
    "/{report_id}",
    status_code=204,
    summary="Удаление отчёта",
    description="Удаляет отчёт и связанные снимки экрана.",
)
def delete_report(
    report_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    if not delete_agent_report(db, report_id, settings):
        raise HTTPException(status_code=404, detail="отчёт не найден")
    return Response(status_code=204)
