"""Ollama runtime and database backups, from the panel."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, DocsOwnerDep
from app.config import Settings, get_settings
from app.services import runtime
from app.services.backup import BackupError, list_backups, resolve_backup, restore, take

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"], dependencies=[AuthDep])


class LoadedOut(BaseModel):
    name: str
    context: int
    size_bytes: int = 0


class RuntimeOut(BaseModel):
    reachable: bool
    base_url: str
    models: list[str]
    loaded: list[LoadedOut]
    detail: str | None = None
    model: str
    context: int | None = None


class ContextIn(BaseModel):
    context: int = Field(ge=4096, le=40960)
    model: str | None = None


class BackupOut(BaseModel):
    name: str
    bytes: int
    taken_at: str


class RestoreIn(BaseModel):
    name: str


@router.get("/runtime", response_model=RuntimeOut)
def read_runtime(settings: Settings = Depends(get_settings)) -> RuntimeOut:
    seen = runtime.probe(settings)
    return RuntimeOut(
        reachable=seen.reachable,
        base_url=seen.base_url,
        models=seen.models,
        loaded=[
            LoadedOut(name=one.name, context=one.context, size_bytes=one.size_bytes)
            for one in seen.loaded
        ],
        detail=seen.detail,
        model=settings.agent_model,
        context=seen.context_of(settings.agent_model),
    )


@router.post("/runtime/context", response_model=RuntimeOut)
def set_context(payload: ContextIn, settings: Settings = Depends(get_settings)) -> RuntimeOut:
    model = payload.model or settings.agent_model
    try:
        runtime.load_with_context(model, payload.context, settings)
    except runtime.RuntimeError_ as exc:
        raise HTTPException(status_code=503 if exc.retryable else 409, detail=str(exc)) from exc
    return read_runtime(settings)


@router.get("/backups", response_model=list[BackupOut])
def backups(settings: Settings = Depends(get_settings)) -> list[BackupOut]:
    return [
        BackupOut(name=b.database.name, bytes=b.bytes, taken_at=b.taken_at.isoformat())
        for b in list_backups(settings)
    ]


@router.post("/backups", response_model=BackupOut)
def take_backup(settings: Settings = Depends(get_settings)) -> BackupOut:
    try:
        backup = take(settings)
    except BackupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return BackupOut(
        name=backup.database.name,
        bytes=backup.bytes,
        taken_at=backup.taken_at.isoformat(),
    )


@router.post("/backups/restore", dependencies=[DocsOwnerDep])
def restore_backup(payload: RestoreIn, settings: Settings = Depends(get_settings)) -> dict[str, str]:
    try:
        archive = resolve_backup(settings, payload.name)
        target = restore(archive, settings)
    except BackupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"restored": str(target)}
