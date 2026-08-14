"""Proxy management endpoints."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_db
from app.api.schemas import ProxyIn, ProxyOut, ProxyUpdate
from app.db import Account, Proxy
from app.geo.country_codes import countries_mismatch
from app.proxies.pool import HealthSnapshot, health_check_record, upsert_proxy

router = APIRouter(prefix="/api/proxies", tags=["proxies"], dependencies=[AuthDep])


def _geo_mismatch(proxy: Proxy, snapshot: HealthSnapshot | None = None) -> bool:
    actual = snapshot.country if snapshot is not None else proxy.last_geo_country
    return countries_mismatch(proxy.country, actual)


def _proxy_account_counts(db: Session) -> dict[int, int]:
    rows = db.execute(
        select(Account.proxy_id, func.count(Account.id))
        .where(Account.proxy_id.isnot(None))
        .group_by(Account.proxy_id)
    ).all()
    return {int(pid): int(n) for pid, n in rows if pid is not None}


def _to_proxy_out(
    proxy: Proxy,
    *,
    accounts_count: int = 0,
    snapshot: HealthSnapshot | None = None,
) -> ProxyOut:
    data = ProxyOut.model_validate(proxy).model_dump()
    data["accounts_count"] = accounts_count
    data["geo_mismatch_warning"] = _geo_mismatch(proxy, snapshot)
    if snapshot is not None:
        data["instagram_reachable"] = snapshot.instagram_reachable
    return ProxyOut.model_validate(data)


@router.get("", response_model=List[ProxyOut])
def list_proxies(db: Session = Depends(get_db)) -> List[ProxyOut]:
    counts = _proxy_account_counts(db)
    rows = db.scalars(select(Proxy).order_by(Proxy.label)).all()
    return [_to_proxy_out(p, accounts_count=counts.get(p.id, 0)) for p in rows]


@router.post("", response_model=ProxyOut)
def create_proxy(payload: ProxyIn, db: Session = Depends(get_db)) -> ProxyOut:
    proxy = upsert_proxy(
        db,
        label=payload.label,
        url=payload.url,
        country=payload.country,
        timezone_name=payload.timezone,
        notes=payload.notes,
    )
    if not payload.skip_health_check:
        _ok, snapshot, _err = health_check_record(db, proxy)
        db.refresh(proxy)
    else:
        snapshot = None
    counts = _proxy_account_counts(db)
    return _to_proxy_out(proxy, accounts_count=counts.get(proxy.id, 0), snapshot=snapshot)


@router.put("/{label}", response_model=ProxyOut)
def update_proxy(label: str, payload: ProxyUpdate, db: Session = Depends(get_db)) -> ProxyOut:
    existing = db.scalar(select(Proxy).where(Proxy.label == label))
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Proxy '{label}' not found")
    proxy = upsert_proxy(
        db,
        label=label,
        url=payload.url,
        country=payload.country,
        timezone_name=payload.timezone,
        notes=payload.notes,
    )
    snapshot = None
    if not payload.skip_health_check:
        _ok, snapshot, _err = health_check_record(db, proxy)
        db.refresh(proxy)
    counts = _proxy_account_counts(db)
    return _to_proxy_out(proxy, accounts_count=counts.get(proxy.id, 0), snapshot=snapshot)


@router.delete("/{label}")
def delete_proxy(label: str, db: Session = Depends(get_db)) -> dict[str, bool]:
    proxy = db.scalar(select(Proxy).where(Proxy.label == label))
    if proxy is None:
        raise HTTPException(status_code=404, detail=f"Proxy '{label}' not found")
    n_accounts = db.scalar(select(func.count()).select_from(Account).where(Account.proxy_id == proxy.id)) or 0
    if n_accounts > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Proxy '{label}' is used by {n_accounts} account(s); reassign or remove them first",
        )
    db.delete(proxy)
    db.commit()
    return {"ok": True}


@router.post("/{label}/check", response_model=ProxyOut)
def check_proxy(label: str, db: Session = Depends(get_db)) -> ProxyOut:
    proxy = db.scalar(select(Proxy).where(Proxy.label == label))
    if proxy is None:
        raise HTTPException(status_code=404, detail=f"Proxy '{label}' not found")
    _ok, snapshot, _err = health_check_record(db, proxy)
    db.refresh(proxy)
    counts = _proxy_account_counts(db)
    return _to_proxy_out(proxy, accounts_count=counts.get(proxy.id, 0), snapshot=snapshot)
