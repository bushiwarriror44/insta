"""Qubax video studio API."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, OwnerOrOpenDep, get_db
from app.api.request_origin import public_origin
from app.api.schemas import (
    QubaxApiKeyIn,
    QubaxBatchCreateIn,
    QubaxEstimateIn,
    QubaxEstimateLineOut,
    QubaxEstimateOut,
    QubaxFormState,
    QubaxImportOut,
    QubaxJobCreateIn,
    QubaxJobListOut,
    QubaxJobOut,
    QubaxMarketModelOut,
    QubaxModelOut,
    QubaxModelsOut,
    QubaxPanelSettingsOut,
    QubaxStatusOut,
)
from app.config import settings
from app.db.models import AssetKind, AssetSource, MediaAsset, QubaxVideoJob
from app.generation.download import download_url
from app.panel.settings_store import (
    get_qubax_last_form,
    qubax_key_from_env,
    resolve_qubax_api_key,
    resolve_qubax_api_public_base,
    resolve_qubax_default_model,
    set_qubax_api_key,
    set_qubax_last_form,
)
from app.services import qubax as qx
from app.services.http import client as http_client
from app.services.media import probe_video

router = APIRouter(prefix="/api/qubax", tags=["qubax"], dependencies=[AuthDep])


def _key_or_400(db: Session) -> str:
    key = resolve_qubax_api_key(db)
    if not key:
        raise HTTPException(
            status_code=400,
            detail="Не задан API-ключ Qubax. Укажите QUBAX_API_KEY или сохраните ключ на странице Qubax.",
        )
    return key


def _raise_qx(exc: qx.QubaxError) -> None:
    code = 502
    if exc.status_code in (401, 403):
        code = 401
    elif exc.status_code == 404:
        code = 404
    elif exc.status_code == 400:
        code = 400
    elif exc.status_code == 402:
        code = 402
    elif exc.status_code == 504:
        code = 504
    raise HTTPException(status_code=code, detail=str(exc)) from exc


def _params_dict(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _job_out(row: QubaxVideoJob) -> QubaxJobOut:
    return QubaxJobOut(
        id=row.id,
        external_id=row.external_id,
        model=row.model,
        prompt=row.prompt,
        status=row.status,
        video_url=row.video_url,
        last_error=row.last_error,
        media_asset_id=row.media_asset_id,
        params=_params_dict(row.params_json),
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def _last_form_out(db: Session) -> QubaxFormState | None:
    raw = get_qubax_last_form(db)
    if not raw:
        return None
    try:
        return QubaxFormState.model_validate(raw)
    except Exception:
        return None


def _normalize_status(body: dict[str, Any]) -> str:
    return str(body.get("status") or "pending").lower()


def _apply_remote(row: QubaxVideoJob, body: dict[str, Any], *, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    status = _normalize_status(body)
    row.status = status
    url = qx.extract_video_url(body)
    if url:
        row.video_url = url
    err = body.get("error") or body.get("message")
    if qx.is_terminal_status(status) and status != "completed":
        row.last_error = str(err or "генерация не удалась")[:2000]
        row.completed_at = row.completed_at or now
    elif status == "completed":
        row.last_error = None
        row.completed_at = row.completed_at or now


def _refresh_job(db: Session, row: QubaxVideoJob, key: str) -> QubaxVideoJob:
    if qx.is_terminal_status(row.status):
        return row
    try:
        body = qx.get_video_job(key, row.external_id)
    except qx.QubaxError as exc:
        row.last_error = str(exc)[:500]
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    _apply_remote(row, body)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _panel_settings_out(db: Session, request: Request | None = None) -> QubaxPanelSettingsOut:
    pub, source = resolve_qubax_api_public_base(db)
    form = get_qubax_last_form(db) or {}
    panel_url = str(form.get("api_public_base_url") or "").strip()
    suggested = public_origin(request) if request is not None else ""
    return QubaxPanelSettingsOut(
        api_public_base_url=panel_url or pub,
        api_public_source=source,
        api_public_configured=bool(pub),
        suggested_api_public_base_url=suggested,
        docs_url=qx.QUBAX_DOCS_URL,
        default_model=resolve_qubax_default_model(db, i2v=False),
        default_model_i2v=resolve_qubax_default_model(db, i2v=True),
    )


def _status_payload(db: Session, request: Request | None = None) -> QubaxStatusOut:
    last_form = _last_form_out(db)
    panel_settings = _panel_settings_out(db, request)
    key = resolve_qubax_api_key(db)
    if not key:
        return QubaxStatusOut(
            configured=False,
            key_from_env=False,
            last_form=last_form,
            settings=panel_settings,
        )
    try:
        bal = qx.billing_balance(key)
        return QubaxStatusOut(
            configured=True,
            key_from_env=qubax_key_from_env(),
            balance=bal,
            last_form=last_form,
            settings=panel_settings,
        )
    except qx.QubaxError as exc:
        return QubaxStatusOut(
            configured=True,
            key_from_env=qubax_key_from_env(),
            last_form=last_form,
            settings=panel_settings,
            error=str(exc),
        )


def _image_url_for(db: Session, image_filename: str | None) -> str | None:
    name = (image_filename or "").strip()
    if not name:
        return None
    try:
        safe = qx.resolve_image_filename_for_job(name)
        pub_base, _ = resolve_qubax_api_public_base(db)
        return qx.public_reference_url(safe, public_base=pub_base or None)
    except qx.QubaxError as exc:
        raise HTTPException(status_code=exc.status_code or 400, detail=str(exc)) from exc


@router.get("/status", response_model=QubaxStatusOut)
def status(
    request: Request,
    db: Session = Depends(get_db),
) -> QubaxStatusOut:
    return _status_payload(db, request)


@router.put("/form", response_model=QubaxStatusOut)
def put_form(
    payload: QubaxFormState,
    request: Request,
    db: Session = Depends(get_db),
) -> QubaxStatusOut:
    data = payload.model_dump(exclude_none=True)
    if payload.image_filename == "":
        data["image_filename"] = ""
    set_qubax_last_form(db, data, merge=True)
    return _status_payload(db, request)


@router.put("/api-key", response_model=QubaxStatusOut, dependencies=[OwnerOrOpenDep])
def put_api_key(
    payload: QubaxApiKeyIn,
    request: Request,
    db: Session = Depends(get_db),
) -> QubaxStatusOut:
    if qubax_key_from_env():
        raise HTTPException(
            status_code=409,
            detail="Ключ задан в QUBAX_API_KEY — изменить из панели нельзя.",
        )
    set_qubax_api_key(db, payload.api_key)
    return _status_payload(db, request)


@router.get("/models", response_model=QubaxModelsOut)
def list_models(
    db: Session = Depends(get_db),
    refresh: bool = Query(default=False),
) -> QubaxModelsOut:
    key = _key_or_400(db)
    try:
        rows = qx.list_models(key, refresh=refresh)
    except qx.QubaxError as exc:
        _raise_qx(exc)
    presets = [
        QubaxModelOut(id=p["id"], owned_by="preset", label=p.get("label"))
        for p in qx.CURATED_PRESETS
    ]
    models = [
        QubaxModelOut(
            id=str(r.get("id") or ""),
            owned_by=str(r.get("owned_by") or ""),
            label=r.get("label") if isinstance(r.get("label"), str) else None,
        )
        for r in rows
        if str(r.get("id") or "")
    ]
    return QubaxModelsOut(presets=presets, models=models)


@router.get("/models/{model_id}")
def model_detail(model_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    key = _key_or_400(db)
    try:
        detail = qx.model_detail(key, model_id)
        market = qx.market_model(model_id)
        merged = {**detail, "market": market}
        if market.get("price") is not None:
            merged["price"] = market.get("price")
            merged["unit"] = market.get("unit")
        return merged
    except qx.QubaxError as exc:
        _raise_qx(exc)


def _opt_float(raw: object) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


@router.get("/market/models/{model_id}", response_model=QubaxMarketModelOut)
def market_model_detail(model_id: str) -> QubaxMarketModelOut:
    row = qx.market_model(model_id)
    return QubaxMarketModelOut(
        id=str(row.get("id") or model_id),
        name=row.get("name") if isinstance(row.get("name"), str) else None,
        price=_opt_float(row.get("price")),
        unit=row.get("unit") if isinstance(row.get("unit"), str) else None,
        benchmark=_opt_float(row.get("benchmark")),
        discount_pct=_opt_float(row.get("discount_pct")),
    )


@router.get("/market/prices")
def market_prices(refresh: bool = Query(default=False)) -> dict[str, Any]:
    prices = qx.market_prices_map(refresh=refresh)
    return {"prices": prices}


@router.post("/estimate", response_model=QubaxEstimateOut)
def estimate_cost(payload: QubaxEstimateIn, db: Session = Depends(get_db)) -> QubaxEstimateOut:
    lines: list[tuple[str, str | None]] = []
    if payload.include_single and (payload.model or "").strip():
        dur = (payload.duration or "5s").strip()
        lines.append((payload.model.strip(), dur))
    for v in payload.variants:
        mid = (v.model or "").strip()
        if not mid:
            continue
        lines.append((mid, (v.duration or payload.duration or "5s").strip()))
    items_raw, total_usd, jobs_count = qx.estimate_jobs(lines)
    balance_usd: float | None = None
    sufficient: bool | None = None
    key = resolve_qubax_api_key(db)
    if key:
        try:
            balance_usd = qx.billing_balance(key)
        except qx.QubaxError:
            balance_usd = None
    if balance_usd is not None and total_usd is not None:
        sufficient = balance_usd >= total_usd
    items = [QubaxEstimateLineOut(**row) for row in items_raw]
    return QubaxEstimateOut(
        items=items,
        total_usd=total_usd,
        balance_usd=balance_usd,
        sufficient=sufficient,
        jobs_count=jobs_count,
    )


def _submit_one(
    db: Session,
    key: str,
    payload: QubaxJobCreateIn,
) -> QubaxVideoJob:
    image_url = _image_url_for(db, payload.image_filename)
    duration = (payload.duration or "5s").strip()
    aspect = (payload.aspect_ratio or "9:16").strip()
    params = {
        "duration": duration,
        "aspect_ratio": aspect,
        "image_filename": (payload.image_filename or "").strip() or None,
        "batch_label": (payload.batch_label or "").strip() or None,
    }
    try:
        remote = qx.create_video(
            key,
            model=payload.model,
            prompt=payload.prompt,
            duration=duration,
            aspect_ratio=aspect,
            image_url=image_url,
        )
    except qx.QubaxError as exc:
        _raise_qx(exc)
    external = str(remote.get("id") or "")
    if not external:
        raise HTTPException(status_code=502, detail="Qubax не вернул id задачи")
    row = QubaxVideoJob(
        external_id=external,
        model=payload.model.strip(),
        prompt=payload.prompt.strip(),
        params_json=json.dumps(params, ensure_ascii=False),
        status=_normalize_status(remote),
        video_url=remote.get("video_url"),
    )
    _apply_remote(row, remote)
    db.add(row)
    db.commit()
    db.refresh(row)
    set_qubax_last_form(
        db,
        {
            "mode": "i2v" if image_url else "t2v",
            "model": payload.model,
            "prompt": payload.prompt,
            "duration": duration,
            "aspect_ratio": aspect,
            "image_filename": payload.image_filename,
        },
    )
    return row


@router.post("/jobs", response_model=QubaxJobOut)
def create_job(payload: QubaxJobCreateIn, db: Session = Depends(get_db)) -> QubaxJobOut:
    key = _key_or_400(db)
    row = _submit_one(db, key, payload)
    return _job_out(row)


@router.post("/jobs/batch", response_model=QubaxJobListOut)
def create_batch(payload: QubaxBatchCreateIn, db: Session = Depends(get_db)) -> QubaxJobListOut:
    key = _key_or_400(db)
    items: list[QubaxVideoJob] = []
    variant_models: list[str] = []
    for variant in payload.variants:
        job_in = QubaxJobCreateIn(
            model=variant.model,
            prompt=payload.prompt,
            duration=variant.duration,
            aspect_ratio=variant.aspect_ratio,
            image_filename=payload.image_filename,
            batch_label=variant.batch_label,
        )
        row = _submit_one(db, key, job_in)
        items.append(row)
        variant_models.append(variant.model)
    set_qubax_last_form(
        db,
        {
            "prompt": payload.prompt,
            "image_filename": payload.image_filename,
            "variant_models": variant_models,
        },
    )
    return QubaxJobListOut(items=[_job_out(r) for r in items], total=len(items))


@router.get("/jobs", response_model=QubaxJobListOut)
def list_jobs(
    db: Session = Depends(get_db),
    limit: int = Query(default=40, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status_filter: str | None = Query(default=None, alias="status"),
    sync_active: bool = Query(default=False),
) -> QubaxJobListOut:
    stmt = select(QubaxVideoJob).order_by(QubaxVideoJob.created_at.desc())
    count_stmt = select(func.count()).select_from(QubaxVideoJob)
    if status_filter:
        stmt = stmt.where(QubaxVideoJob.status == status_filter.strip().lower())
        count_stmt = count_stmt.where(QubaxVideoJob.status == status_filter.strip().lower())
    total = int(db.scalar(count_stmt) or 0)
    rows = list(db.scalars(stmt.offset(offset).limit(limit)).all())
    if sync_active and rows:
        key = resolve_qubax_api_key(db)
        if key:
            for row in rows:
                if not qx.is_terminal_status(row.status):
                    _refresh_job(db, row, key)
    return QubaxJobListOut(items=[_job_out(r) for r in rows], total=total)


@router.get("/jobs/{job_id}", response_model=QubaxJobOut)
def get_job(job_id: int, db: Session = Depends(get_db)) -> QubaxJobOut:
    row = db.get(QubaxVideoJob, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    key = _key_or_400(db)
    row = _refresh_job(db, row, key)
    return _job_out(row)


@router.post("/jobs/{job_id}/import", response_model=QubaxImportOut)
def import_job(job_id: int, db: Session = Depends(get_db)) -> QubaxImportOut:
    row = db.get(QubaxVideoJob, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    key = _key_or_400(db)
    row = _refresh_job(db, row, key)
    if row.status != "completed" or not row.video_url:
        raise HTTPException(status_code=409, detail="Видео ещё не готово")
    if row.media_asset_id is not None:
        asset = db.get(MediaAsset, row.media_asset_id)
        if asset is not None:
            return QubaxImportOut(
                job_id=row.id, media_asset_id=asset.id, filename=asset.filename
            )
    final_name = f"{uuid.uuid4().hex}.mp4"
    dest = settings.media_dir / final_name
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    with http_client(settings, timeout=300) as client:
        try:
            download_url(client, row.video_url, dest, name="qubax")
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    probe = probe_video(dest)
    params = _params_dict(row.params_json)
    asset = MediaAsset(
        filename=final_name,
        kind=AssetKind.video,
        source=AssetSource.generated,
        label=str(params.get("batch_label") or f"qubax:{row.model}")[:120],
        generator=row.model,
        prompt=row.prompt,
        duration_s=probe.duration_s,
        width=probe.width,
        height=probe.height,
    )
    db.add(asset)
    db.flush()
    row.media_asset_id = asset.id
    db.add(row)
    db.commit()
    return QubaxImportOut(job_id=row.id, media_asset_id=asset.id, filename=final_name)
