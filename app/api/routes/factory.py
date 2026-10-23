"""Content-agent, generation and composition API."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.presets import seed_if_empty
from app.api.deps import AuthDep, get_db
from app.config import settings
from app.db.models import (
    Account,
    AgentRun,
    AssetKind,
    ChannelSource,
    Clarification,
    Composition,
    CompositionClip,
    GenerationJob,
    MediaAsset,
    PipelineStatus,
    PlanJob,
    PromptPreset,
    SourceKind,
)
from app.generation.hints import enrich_generation_error
from app.generation.local_offer import should_offer_local_switch
from app.generation.registry import available_backends, describe_backends, get_backend
from app.agent.sources import SourceError, read_source
from app.services.clarifications import answer as answer_clarification
from app.services.clarifications import open_questions
from app.services.planning import plan_for_channel
from app.services.retry import NotRetriable, revive


def _generation_http_detail(detail: str, backend: str) -> str:
    if (backend or "").strip().lower() == "slideshow":
        return detail
    return enrich_generation_error(detail, backend=backend)


def _generation_row(job: GenerationJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "status": job.status.value,
        "prompt": job.prompt,
        "stage": job.stage,
        "queue_position": job.queue_position,
        "post_title": job.post_title,
        "last_error": job.last_error,
        "cost_usd": job.cost_usd,
        "backend": job.backend,
        "asset_id": job.asset_id,
        "offer_local_switch": should_offer_local_switch(job, settings),
    }


router = APIRouter(tags=["factory"], dependencies=[AuthDep])


class PlanIn(BaseModel):
    count: int = Field(default=5, ge=1, le=20)
    duration_s: float = Field(default=5.0, ge=5, le=10)
    auto_schedule: bool = True
    spread_over_days: Optional[int] = Field(default=None, ge=1, le=14)


class BriefIn(BaseModel):
    brief: str = ""


class SourceIn(BaseModel):
    kind: str
    value: str
    label: str = ""


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1)


class SourcePatch(BaseModel):
    enabled: Optional[bool] = None
    label: Optional[str] = None


class GenerationCreate(BaseModel):
    prompt: str = Field(min_length=1)
    negative_prompt: str = ""
    backend: str = "auto"
    duration_s: float = Field(default=5.0, ge=5, le=30)
    width: int = Field(default=720, ge=256, le=1920)
    height: int = Field(default=1280, ge=256, le=1920)
    seed: Optional[int] = None
    account_id: Optional[int] = None
    input_mode: Optional[str] = None
    reference_asset_id: Optional[int] = None
    reference_filename: Optional[str] = None
    reference_filenames: Optional[list[str]] = None
    reference_role: str = "start_image"
    audio_mode: str = "none"
    audio_filename: Optional[str] = None


class GenerationRetryIn(BaseModel):
    backend: Optional[str] = None


class CompositionIn(BaseModel):
    clip_ids: list[int] = Field(min_length=2)
    audio_asset_id: Optional[int] = None
    account_id: Optional[int] = None
    post_title: str = ""
    width: int = Field(default=1080, ge=256, le=1920)
    height: int = Field(default=1920, ge=256, le=1920)


class AgentSettingsIn(BaseModel):
    brief: Optional[str] = None
    hold_for_review: Optional[bool] = None
    daily_spend_cap_usd: Optional[float] = Field(default=None, ge=0)


def _account(db: Session, account_id: int) -> Account:
    row = db.get(Account, account_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Аккаунт не найден")
    return row


@router.post("/api/accounts/{account_id}/plan")
def queue_plan(account_id: int, payload: PlanIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    account = _account(db, account_id)
    job = PlanJob(
        account_id=account.id,
        count=payload.count,
        duration_s=payload.duration_s,
        auto_schedule=payload.auto_schedule,
        spread_over_days=payload.spread_over_days,
        status=PipelineStatus.queued,
        scheduled_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return {"id": job.id, "status": job.status.value, "count": job.count}


@router.post("/api/accounts/{account_id}/preview")
def preview_plan(account_id: int, payload: PlanIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    account = _account(db, account_id)
    try:
        jobs = plan_for_channel(
            db,
            account,
            payload.count,
            duration_s=payload.duration_s,
            auto_schedule=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"planned": len(jobs), "job_ids": [j.id for j in jobs]}


@router.post("/api/accounts/{account_id}/week")
def queue_week(account_id: int, payload: PlanIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    payload = payload.model_copy(update={"spread_over_days": payload.spread_over_days or 7})
    return queue_plan(account_id, payload, db)


@router.get("/api/accounts/{account_id}/plans")
def list_plans(account_id: int, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    _account(db, account_id)
    rows = db.scalars(
        select(PlanJob)
        .where(PlanJob.account_id == account_id)
        .order_by(PlanJob.created_at.desc())
        .limit(50)
    ).all()
    return [
        {
            "id": row.id,
            "status": row.status.value,
            "count": row.count,
            "planned": row.planned,
            "spread_over_days": row.spread_over_days,
            "last_error": row.last_error,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


@router.post("/api/plans/{job_id}/cancel")
def cancel_plan(job_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    job = db.get(PlanJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="План не найден")
    if job.status not in (
        PipelineStatus.queued,
        PipelineStatus.failed,
        PipelineStatus.dead,
    ):
        raise HTTPException(
            status_code=409,
            detail=f"задачу в состоянии «{job.status.value}» отменить нельзя",
        )
    job.status = PipelineStatus.cancelled
    db.commit()
    return {"id": job.id, "status": job.status.value}


@router.patch("/api/accounts/{account_id}/brief")
def update_brief(account_id: int, payload: BriefIn, db: Session = Depends(get_db)) -> dict[str, str]:
    account = _account(db, account_id)
    account.brief = (payload.brief or "").strip()
    db.commit()
    return {"brief": account.brief}


@router.get("/api/accounts/{account_id}/questions")
def list_questions(account_id: int, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    account = _account(db, account_id)
    rows = open_questions(db, account.id)
    return [
        {
            "id": r.id,
            "question": r.question,
            "why": r.why,
            "assumed": r.assumed,
            "open": r.open,
        }
        for r in rows
    ]


@router.get("/api/accounts/{account_id}/sources")
def list_sources(account_id: int, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    account = _account(db, account_id)
    rows = db.scalars(select(ChannelSource).where(ChannelSource.account_id == account.id)).all()
    return [
        {
            "id": r.id,
            "kind": r.kind.value if hasattr(r.kind, "value") else r.kind,
            "value": r.value,
            "label": r.label,
            "enabled": r.enabled,
            "last_status": r.last_status,
        }
        for r in rows
    ]


@router.post("/api/accounts/{account_id}/sources")
def add_source(account_id: int, payload: SourceIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    account = _account(db, account_id)
    try:
        kind = SourceKind(payload.kind)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="тип источника должен быть url или file",
        ) from exc
    value = (payload.value or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="значение источника не может быть пустым")
    row = ChannelSource(
        account_id=account.id,
        kind=kind,
        value=value,
        label=(payload.label or "").strip(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "kind": payload.kind, "value": row.value, "label": row.label}


@router.post("/api/questions/{question_id}/answer")
def answer_question(question_id: int, payload: AnswerIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.get(Clarification, question_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Вопрос не найден")
    saved = answer_clarification(db, row, payload.answer, by="operator")
    return {"id": saved.id, "answer": saved.answer}


@router.get("/api/agent-runs")
def list_agent_runs(
    account_id: Optional[int] = Query(default=None),
    username: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    stmt = select(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit)
    if account_id is not None:
        stmt = stmt.where(AgentRun.account_id == account_id)
    elif username:
        account = db.scalar(select(Account).where(Account.username == username))
        if account is None:
            return []
        stmt = stmt.where(AgentRun.account_id == account.id)
    rows = db.scalars(stmt).all()
    out = []
    for r in rows:
        acc = db.get(Account, r.account_id)
        out.append(
            {
                "id": r.id,
                "account_username": acc.username if acc else None,
                "ok": r.ok,
                "model": r.model,
                "requested": r.requested,
                "returned": r.returned,
                "cost_usd": r.cost_usd,
                "error": r.error,
                "created_at": r.created_at,
            }
        )
    return out


@router.get("/api/agent-runs/{run_id}")
def get_agent_run(run_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    run = db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Прогон не найден")
    return {"id": run.id, "ok": run.ok, "prompt": run.prompt, "raw": run.raw, "ideas": run.ideas, "questions": run.questions, "error": run.error, "cost_usd": run.cost_usd, "duration_ms": run.duration_ms, "sources": run.sources}


@router.patch("/api/accounts/{account_id}/agent-settings")
def update_agent_settings(
    account_id: int, payload: AgentSettingsIn, db: Session = Depends(get_db)
) -> dict[str, Any]:
    account = _account(db, account_id)
    if payload.brief is not None:
        account.brief = (payload.brief or "").strip()
    if payload.hold_for_review is not None:
        account.hold_for_review = payload.hold_for_review
    if payload.daily_spend_cap_usd is not None:
        account.daily_spend_cap_usd = payload.daily_spend_cap_usd
    db.commit()
    return {
        "id": account.id,
        "brief": account.brief,
        "hold_for_review": account.hold_for_review,
        "daily_spend_cap_usd": account.daily_spend_cap_usd,
    }


@router.patch("/api/sources/{source_id}")
def patch_source(source_id: int, payload: SourcePatch, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.get(ChannelSource, source_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Источник не найден")
    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.label is not None:
        row.label = payload.label
    db.commit()
    return {"id": row.id, "enabled": row.enabled, "label": row.label, "last_status": row.last_status}


@router.post("/api/sources/{source_id}/check")
def check_source(source_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.get(ChannelSource, source_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Источник не найден")
    try:
        read_source(row.kind, row.value, row.label, settings)
        row.last_status = "ok"
    except SourceError as exc:
        row.last_status = str(exc)[:200]
    row.last_read_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": row.id, "last_status": row.last_status}


@router.post("/api/sources/{source_id}/read")
def read_one_source(source_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.get(ChannelSource, source_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Источник не найден")
    try:
        seen = read_source(row.kind, row.value, row.label, settings)
    except SourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"label": seen.label, "origin": seen.origin, "text": seen.text, "characters": len(seen.text)}


@router.get("/api/assets")
def list_assets(
    kind: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    stmt = select(MediaAsset).where(MediaAsset.file_removed_at.is_(None)).order_by(MediaAsset.created_at.desc()).limit(limit)
    if kind:
        try:
            kind_enum = AssetKind(kind)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"неизвестный тип медиа: {kind}",
            ) from exc
        stmt = stmt.where(MediaAsset.kind == kind_enum)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(MediaAsset.prompt.ilike(like) | MediaAsset.label.ilike(like) | MediaAsset.filename.ilike(like))
    rows = db.scalars(stmt).all()
    return [
        {
            "id": r.id,
            "filename": r.filename,
            "kind": r.kind.value,
            "source": r.source.value,
            "label": r.label,
            "prompt": r.prompt,
            "duration_s": r.duration_s,
            "width": r.width,
            "height": r.height,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/api/generations/backends")
def list_generation_backends() -> list[dict[str, Any]]:
    return describe_backends(settings)


@router.post("/api/generations")
def create_generation(payload: GenerationCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    if payload.backend not in available_backends():
        raise HTTPException(status_code=400, detail=f"неизвестный бэкенд {payload.backend!r}")
    if payload.account_id is not None:
        _account(db, payload.account_id)
    from app.generation.base import INPUT_MODE_SLIDESHOW, GenerationError
    from app.services.generation_inputs import apply_job_reference_fields, ensure_job_references

    audio_mode = (payload.audio_mode or "none").strip().lower()
    if audio_mode not in {"none", "generate", "library"}:
        raise HTTPException(status_code=400, detail="audio_mode: none, generate или library")
    audio_filename = (payload.audio_filename or "").strip() or None
    if audio_mode == "library":
        if not audio_filename:
            raise HTTPException(status_code=400, detail="для звука из библиотеки нужен файл")
        from app.video.mux_audio import MuxError, resolve_audio_file

        try:
            resolve_audio_file(audio_filename, settings)
        except MuxError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    job = GenerationJob(
        prompt=payload.prompt,
        negative_prompt=payload.negative_prompt,
        backend=payload.backend,
        duration_s=payload.duration_s,
        width=payload.width,
        height=payload.height,
        seed=payload.seed,
        account_id=payload.account_id,
        audio_mode=audio_mode,
        audio_filename=audio_filename,
        status=PipelineStatus.queued,
        stage="в очереди",
        scheduled_at=datetime.now(timezone.utc),
    )
    names = [name.strip() for name in (payload.reference_filenames or []) if name and name.strip()]
    if len(names) > 8:
        raise HTTPException(status_code=400, detail="не больше 8 референсов")
    apply_job_reference_fields(
        job,
        input_mode=payload.input_mode,
        reference_asset_id=payload.reference_asset_id,
        reference_filename=payload.reference_filename,
        reference_filenames=names or None,
        reference_role=payload.reference_role,
    )
    if job.input_mode == INPUT_MODE_SLIDESHOW:
        job.backend = "slideshow"
    try:
        ensure_job_references(db, job, settings)
    except GenerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    engine = get_backend(job.backend, settings)
    if not engine.healthcheck():
        raise HTTPException(
            status_code=409,
            detail=_generation_http_detail(engine.health_detail(), job.backend),
        )
    db.add(job)
    db.commit()
    db.refresh(job)
    return {
        "id": job.id,
        "status": job.status.value,
        "prompt": job.prompt,
        "backend": job.backend,
        "input_mode": job.input_mode,
    }


@router.post("/api/generations/{job_id}/cancel")
def cancel_generation(job_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    job = db.get(GenerationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Рендер не найден")
    # Same dismiss policy as publish jobs: queued or already-failed rows can
    # be cleared; running work must finish or be reclaimed by the worker.
    if job.status not in (
        PipelineStatus.queued,
        PipelineStatus.failed,
        PipelineStatus.dead,
    ):
        raise HTTPException(status_code=409, detail=f"задачу в состоянии «{job.status.value}» отменить нельзя")
    job.status = PipelineStatus.cancelled
    db.commit()
    return {"id": job.id, "status": job.status.value}


@router.post("/api/generations/{job_id}/retry")
def retry_generation(
    job_id: int,
    payload: GenerationRetryIn | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    job = db.get(GenerationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Рендер не найден")
    if payload and payload.backend:
        name = payload.backend.strip().lower()
        if name not in available_backends():
            raise HTTPException(status_code=400, detail=f"неизвестный бэкенд {name!r}")
        job.backend = name
    from app.generation.base import GenerationError
    from app.services.generation_inputs import ensure_job_references

    try:
        ensure_job_references(db, job, settings)
    except GenerationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    engine = get_backend(job.backend, settings)
    if not engine.healthcheck():
        raise HTTPException(
            status_code=409,
            detail=_generation_http_detail(engine.health_detail(), job.backend),
        )
    try:
        revive(job)
    except NotRetriable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return {"id": job.id, "status": job.status.value}


@router.post("/api/compositions")
def create_composition(payload: CompositionIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    from app.services.media import MediaError, asset_media_path

    assets = {
        asset.id: asset
        for asset in db.scalars(select(MediaAsset).where(MediaAsset.id.in_(payload.clip_ids))).all()
    }
    missing = [clip_id for clip_id in payload.clip_ids if clip_id not in assets]
    if missing:
        raise HTTPException(status_code=404, detail=f"неизвестные клипы: {missing}")
    for clip_id in payload.clip_ids:
        try:
            asset_media_path(settings.media_dir, assets[clip_id])
        except MediaError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    if payload.audio_asset_id is not None:
        audio = db.get(MediaAsset, payload.audio_asset_id)
        if audio is None:
            raise HTTPException(status_code=404, detail=f"саундтрек asset_id={payload.audio_asset_id} не найден")
        try:
            asset_media_path(settings.media_dir, audio)
        except MediaError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    composition = Composition(
        width=payload.width,
        height=payload.height,
        audio_asset_id=payload.audio_asset_id,
        account_id=payload.account_id,
        post_title=payload.post_title,
        status=PipelineStatus.queued,
        scheduled_at=datetime.now(timezone.utc),
    )
    db.add(composition)
    db.flush()
    for index, clip_id in enumerate(payload.clip_ids):
        db.add(CompositionClip(composition_id=composition.id, asset_id=clip_id, position=index))
    db.commit()
    db.refresh(composition)
    return {"id": composition.id, "status": composition.status.value, "clips": len(payload.clip_ids)}


@router.post("/api/compositions/{job_id}/cancel")
def cancel_composition(job_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    job = db.get(Composition, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Склейка не найдена")
    if job.status not in (
        PipelineStatus.queued,
        PipelineStatus.failed,
        PipelineStatus.dead,
    ):
        raise HTTPException(status_code=409, detail=f"задачу в состоянии «{job.status.value}» отменить нельзя")
    job.status = PipelineStatus.cancelled
    db.commit()
    return {"id": job.id, "status": job.status.value}


@router.post("/api/compositions/{job_id}/retry")
def retry_composition(job_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    job = db.get(Composition, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Склейка не найдена")
    from app.services.composing import ensure_composition_media
    from app.services.media import MediaError

    try:
        ensure_composition_media(db, job)
    except MediaError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        revive(job)
    except NotRetriable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return {"id": job.id, "status": job.status.value}


@router.get("/api/generations/{job_id}")
def get_generation(job_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    job = db.get(GenerationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Рендер не найден")
    return _generation_row(job)


@router.get("/api/generations")
def list_generations(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    stmt = select(GenerationJob).order_by(GenerationJob.created_at.desc()).limit(limit)
    if status_filter:
        stmt = stmt.where(GenerationJob.status == PipelineStatus(status_filter))
    rows = db.scalars(stmt).all()
    return [_generation_row(r) for r in rows]


@router.get("/api/compositions")
def list_compositions(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = db.scalars(select(Composition).order_by(Composition.created_at.desc()).limit(limit)).all()
    return [
        {
            "id": r.id,
            "status": r.status.value,
            "post_title": r.post_title,
            "last_error": r.last_error,
            "clips": len(r.clips),
        }
        for r in rows
    ]


@router.get("/api/presets")
def list_presets(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    seed_if_empty(db)
    rows = db.scalars(select(PromptPreset)).all()
    return [{"id": r.id, "name": r.name, "brief": r.brief} for r in rows]
