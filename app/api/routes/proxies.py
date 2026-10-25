"""Proxy management endpoints."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_db
from app.api.schemas import (
    ProxyCheckBatchIn,
    ProxyCheckBatchOut,
    ProxyIn,
    ProxyOut,
    ProxyUpdate,
)
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
    check_detail: str | None = None,
) -> ProxyOut:
    data = ProxyOut.model_validate(proxy).model_dump()
    data["accounts_count"] = accounts_count
    data["geo_mismatch_warning"] = _geo_mismatch(proxy, snapshot)
    if snapshot is not None:
        data["instagram_reachable"] = snapshot.instagram_reachable
        data["instagram_login_ok"] = snapshot.instagram_login_reachable
        data["last_check_ms"] = snapshot.check_ms
        data["latency_ms"] = snapshot.latency_ms
        data["instagram_latency_ms"] = snapshot.instagram_latency_ms
        data["login_page_latency_ms"] = snapshot.login_page_latency_ms
    else:
        data["instagram_reachable"] = proxy.instagram_reachable
        data["instagram_login_ok"] = proxy.instagram_login_ok
        data["last_check_ms"] = proxy.last_check_ms
    detail = check_detail if check_detail is not None else proxy.last_check_detail
    data["check_detail"] = detail
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
    check_detail: str | None = None
    if not payload.skip_health_check:
        _ok, snapshot, check_detail = health_check_record(db, proxy)
        db.refresh(proxy)
    else:
        snapshot = None
    counts = _proxy_account_counts(db)
    return _to_proxy_out(
        proxy,
        accounts_count=counts.get(proxy.id, 0),
        snapshot=snapshot,
        check_detail=check_detail,
    )


@router.put("/{label}", response_model=ProxyOut)
def update_proxy(label: str, payload: ProxyUpdate, db: Session = Depends(get_db)) -> ProxyOut:
    existing = db.scalar(select(Proxy).where(Proxy.label == label))
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Прокси «{label}» не найден")
    proxy = upsert_proxy(
        db,
        label=label,
        url=payload.url,
        country=payload.country,
        timezone_name=payload.timezone,
        notes=payload.notes,
    )
    snapshot = None
    check_detail: str | None = None
    if not payload.skip_health_check:
        _ok, snapshot, check_detail = health_check_record(db, proxy)
        db.refresh(proxy)
    counts = _proxy_account_counts(db)
    return _to_proxy_out(
        proxy,
        accounts_count=counts.get(proxy.id, 0),
        snapshot=snapshot,
        check_detail=check_detail,
    )


@router.delete("/{label}")
def delete_proxy(label: str, db: Session = Depends(get_db)) -> dict[str, bool]:
    proxy = db.scalar(select(Proxy).where(Proxy.label == label))
    if proxy is None:
        raise HTTPException(status_code=404, detail=f"Прокси «{label}» не найден")
    n_accounts = db.scalar(select(func.count()).select_from(Account).where(Account.proxy_id == proxy.id)) or 0
    if n_accounts > 0:
        detail = (
            f"Прокси «{label}» используется {n_accounts} акк. — сначала переназначьте их"
        )
        raise HTTPException(status_code=409, detail=detail)
    db.delete(proxy)
    db.commit()
    return {"ok": True}


@router.post("/check-batch", response_model=ProxyCheckBatchOut)
def check_proxies_batch(
    payload: ProxyCheckBatchIn | None = None, db: Session = Depends(get_db)
) -> ProxyCheckBatchOut:
    """FULL-check many proxies (or all). Sequential to avoid stampeding egress."""
    body = payload or ProxyCheckBatchIn()
    counts = _proxy_account_counts(db)
    if body.labels:
        wanted = [label.strip() for label in body.labels if (label or "").strip()]
        rows = db.scalars(select(Proxy).where(Proxy.label.in_(wanted)).order_by(Proxy.label)).all()
        found = {p.label for p in rows}
        missing = [label for label in wanted if label not in found]
        if missing:
            raise HTTPException(
                status_code=404,
                detail=f"прокси не найдены: {', '.join(missing[:8])}",
            )
    else:
        rows = db.scalars(select(Proxy).order_by(Proxy.label)).all()

    results: list[ProxyOut] = []
    healthy = 0
    failed = 0
    for proxy in rows:
        ok, snapshot, check_detail = health_check_record(db, proxy)
        db.refresh(proxy)
        if ok:
            healthy += 1
        else:
            failed += 1
        results.append(
            _to_proxy_out(
                proxy,
                accounts_count=counts.get(proxy.id, 0),
                snapshot=snapshot,
                check_detail=check_detail,
            )
        )
    return ProxyCheckBatchOut(
        results=results,
        checked=len(results),
        healthy=healthy,
        failed=failed,
    )


@router.post("/{label}/check", response_model=ProxyOut)
def check_proxy(label: str, db: Session = Depends(get_db)) -> ProxyOut:
    proxy = db.scalar(select(Proxy).where(Proxy.label == label))
    if proxy is None:
        raise HTTPException(status_code=404, detail=f"Прокси «{label}» не найден")
    _ok, snapshot, check_detail = health_check_record(db, proxy)
    db.refresh(proxy)
    counts = _proxy_account_counts(db)
    return _to_proxy_out(
        proxy,
        accounts_count=counts.get(proxy.id, 0),
        snapshot=snapshot,
        check_detail=check_detail,
    )
