"""Floppydata rotating proxy: generate credentials and import into panel pool."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, OwnerOrOpenDep, get_db
from app.api.routes.proxies import _proxy_account_counts, _to_proxy_out
from app.api.schemas import (
    FloppydataApiKeyIn,
    FloppydataFormState,
    FloppydataGenerateIn,
    FloppydataGenerateOut,
    FloppydataImportIn,
    FloppydataStatusOut,
    ProxyOut,
)
from app.panel.settings_store import (
    floppydata_key_from_env,
    get_floppydata_last_form,
    resolve_floppydata_api_key,
    set_floppydata_api_key,
    set_floppydata_last_form,
)
from app.proxies.pool import health_check_record, upsert_proxy
from app.services import floppydata as fd

router = APIRouter(prefix="/api/floppydata", tags=["floppydata"], dependencies=[AuthDep])


def _key_or_400(db: Session) -> str:
    key = resolve_floppydata_api_key(db)
    if not key:
        raise HTTPException(
            status_code=400,
            detail="Не задан API-ключ Floppydata. Укажите FLOPPYDATA_API_KEY или сохраните ключ на вкладке Floppydata.",
        )
    return key


def _raise_fd(exc: fd.FloppydataError) -> None:
    code = 502
    if exc.status_code in (401, 403):
        code = 401
    elif exc.status_code == 400:
        code = 400
    raise HTTPException(status_code=code, detail=str(exc)) from exc


def _last_form_out(db: Session) -> FloppydataFormState | None:
    raw = get_floppydata_last_form(db)
    if not raw:
        return None
    try:
        return FloppydataFormState.model_validate(raw)
    except Exception:
        return None


@router.get("/status", response_model=FloppydataStatusOut)
def status(db: Session = Depends(get_db)) -> FloppydataStatusOut:
    last_form = _last_form_out(db)
    key = resolve_floppydata_api_key(db)
    if not key:
        return FloppydataStatusOut(configured=False, key_from_env=False, last_form=last_form)
    try:
        raw = fd.rotating_balance(key)
        flat = fd.normalize_rotating_balance(raw if isinstance(raw, dict) else {})
        return FloppydataStatusOut(
            configured=True,
            key_from_env=floppydata_key_from_env(),
            balance_gb=flat.get("balance_gb"),
            balance_bytes=flat.get("balance_bytes"),
            expiring_gb=flat.get("expiring_gb"),
            expiring_at=flat.get("expiring_at"),
            last_form=last_form,
        )
    except fd.FloppydataError as exc:
        return FloppydataStatusOut(
            configured=True,
            key_from_env=floppydata_key_from_env(),
            last_form=last_form,
            error=str(exc),
        )


@router.put("/api-key", response_model=FloppydataStatusOut, dependencies=[OwnerOrOpenDep])
def put_api_key(
    payload: FloppydataApiKeyIn,
    db: Session = Depends(get_db),
) -> FloppydataStatusOut:
    if floppydata_key_from_env():
        raise HTTPException(
            status_code=400,
            detail="Ключ задан в FLOPPYDATA_API_KEY (env) — смените его в окружении сервера.",
        )
    set_floppydata_api_key(db, payload.api_key)
    return status(db)


@router.get("/locations")
def locations(
    type: str = Query(default="residential", alias="type"),
    db: Session = Depends(get_db),
) -> Any:
    key = _key_or_400(db)
    if type not in ("residential", "mobile", "datacenter"):
        raise HTTPException(status_code=400, detail="type: residential | mobile | datacenter")
    try:
        return fd.list_locations(key, proxy_type=type)
    except fd.FloppydataError as exc:
        _raise_fd(exc)


@router.get("/subusers")
def subusers(db: Session = Depends(get_db)) -> Any:
    key = _key_or_400(db)
    try:
        return fd.list_subusers(key)
    except fd.FloppydataError as exc:
        _raise_fd(exc)


@router.post("/generate", response_model=FloppydataGenerateOut)
def generate(
    payload: FloppydataGenerateIn,
    db: Session = Depends(get_db),
) -> FloppydataGenerateOut:
    key = _key_or_400(db)
    try:
        items = fd.generate_connections(
            key,
            proxy_type=payload.type,
            country=payload.country,
            protocol=payload.protocol,
            rotation=payload.rotation,
            count=payload.count,
            city=payload.city,
            state=payload.state,
            udp=payload.udp,
            subuser_id=payload.subuser_id,
        )
    except fd.FloppydataError as exc:
        _raise_fd(exc)
    missing = [i for i in items if not i.get("connection_string")]
    if missing:
        raise HTTPException(status_code=502, detail="Floppydata не вернул connectionString")
    set_floppydata_last_form(
        db,
        {
            "type": payload.type,
            "country": payload.country,
            "city": payload.city,
            "state": payload.state,
            "protocol": payload.protocol,
            "rotation": payload.rotation,
            "udp": payload.udp,
            "count": payload.count,
            "subuser_id": payload.subuser_id,
        },
    )
    return FloppydataGenerateOut(items=items)  # type: ignore[arg-type]


@router.post("/import", response_model=list[ProxyOut])
def import_proxies(
    payload: FloppydataImportIn,
    db: Session = Depends(get_db),
) -> list[ProxyOut]:
    counts = _proxy_account_counts(db)
    out: list[ProxyOut] = []
    for index, item in enumerate(payload.items, start=1):
        url = (item.url or "").strip()
        if not url:
            continue
        label = (item.label or "").strip() or f"floppy-{index}"
        proxy = upsert_proxy(
            db,
            label=label,
            url=url,
            country=item.country,
            notes="floppydata",
        )
        snapshot = None
        check_detail = None
        if payload.run_health_check:
            _ok, snapshot, check_detail = health_check_record(db, proxy)
            db.refresh(proxy)
        out.append(
            _to_proxy_out(
                proxy,
                accounts_count=counts.get(proxy.id, 0),
                snapshot=snapshot,
                check_detail=check_detail,
            )
        )
    if not out:
        raise HTTPException(status_code=400, detail="Нет URL для импорта")
    if payload.form is not None:
        set_floppydata_last_form(db, payload.form.model_dump())
    return out
