"""Account management endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.connection_test import run_account_connection_test
from app.accounts.first_login_service import run_account_first_login
from app.accounts.session_export import export_sessionid
from app.accounts.session_manager import (
    clear_session_file,
    ensure_fingerprint_and_proxy,
    session_path,
)
from app.api.deps import AuthDep, get_db
from app.api.schemas import (
    AccountConnectionTestOut,
    AccountIn,
    AccountOut,
    AccountProxyUpdate,
    AccountSessionOut,
    AccountSessionUpdate,
    FirstLoginOut,
)
from app.db import Account, AccountStatus, DailyStat, Proxy

router = APIRouter(prefix="/api/accounts", tags=["accounts"], dependencies=[AuthDep])


def _account_session_fields(username: str, db_session_id: str | None):
    path = session_path(username)
    file_exists = path.exists()
    updated_at = None
    if file_exists:
        updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    exported = export_sessionid(username, db_session_id=db_session_id)
    source = exported.source if exported else "none"
    return file_exists, updated_at, source


def _serialize(account: Account, *, db: Session, today: str) -> AccountOut:
    proxy_label = None
    proxy_country = None
    proxy_geo_country = None
    proxy_is_healthy = None
    proxy_last_ip = None
    if account.proxy_id is not None:
        proxy = db.get(Proxy, account.proxy_id)
        if proxy is not None:
            proxy_label = proxy.label
            proxy_country = proxy.country
            proxy_geo_country = proxy.last_geo_country
            proxy_is_healthy = proxy.is_healthy
            proxy_last_ip = proxy.last_known_ip

    stat = db.scalar(
        select(DailyStat).where(
            DailyStat.account_id == account.id,
            DailyStat.date_key == today,
        )
    )
    posts_today = stat.posts_count if stat else 0
    failures_today = stat.failures_count if stat else 0

    file_exists, file_updated_at, session_source = _account_session_fields(
        account.username,
        account.session_id,
    )

    return AccountOut(
        id=account.id,
        username=account.username,
        status=account.status.value,
        proxy_id=account.proxy_id,
        proxy_label=proxy_label,
        proxy_country=proxy_country,
        proxy_geo_country=proxy_geo_country,
        proxy_is_healthy=proxy_is_healthy,
        proxy_last_ip=proxy_last_ip,
        timezone=account.timezone,
        daily_post_cap=account.daily_post_cap,
        min_gap_hours=account.min_gap_hours,
        active_hour_start=account.active_hour_start,
        active_hour_end=account.active_hour_end,
        last_publish_at=account.last_publish_at,
        last_idle_warmup_at=account.last_idle_warmup_at,
        last_session_rotation_at=account.last_session_rotation_at,
        cooldown_until=account.cooldown_until,
        caption_profile=account.caption_profile,
        has_totp=bool(account.totp_seed),
        has_session_id=bool(account.session_id),
        session_file_exists=file_exists,
        session_file_updated_at=file_updated_at,
        session_source=session_source,
        posts_today=posts_today,
        failures_today=failures_today,
    )


@router.get("", response_model=List[AccountOut])
def list_accounts(db: Session = Depends(get_db)) -> List[AccountOut]:
    today = datetime.now(timezone.utc).date().isoformat()
    rows = db.scalars(select(Account).order_by(Account.username)).all()
    return [_serialize(a, db=db, today=today) for a in rows]


@router.post("", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(payload: AccountIn, db: Session = Depends(get_db)) -> AccountOut:
    proxy = db.scalar(select(Proxy).where(Proxy.label == payload.proxy_label))
    if proxy is None:
        raise HTTPException(status_code=400, detail=f"Proxy '{payload.proxy_label}' not found")

    existing = db.scalar(select(Account).where(Account.username == payload.username))
    if existing is not None:
        account = existing
    else:
        account = Account(username=payload.username)
        db.add(account)

    account.password = payload.password
    account.proxy_id = proxy.id
    account.timezone = payload.timezone
    account.daily_post_cap = payload.daily_post_cap
    account.min_gap_hours = payload.min_gap_hours
    account.active_hour_start = payload.active_hour_start
    account.active_hour_end = payload.active_hour_end
    if payload.caption_profile is not None:
        account.caption_profile = payload.caption_profile or None
    if payload.totp_seed is not None:
        account.totp_seed = payload.totp_seed.strip() or None
    if payload.session_id is not None:
        account.session_id = payload.session_id.strip() or None
        if account.session_id:
            clear_session_file(account.username)
    if payload.email is not None:
        account.email = payload.email or None
    if payload.email_password is not None:
        account.email_password = payload.email_password or None
    if account.status == AccountStatus.blocked:
        account.status = AccountStatus.active

    db.commit()
    db.refresh(account)

    ensure_fingerprint_and_proxy(account.username, country=proxy.country or "US")

    today = datetime.now(timezone.utc).date().isoformat()
    return _serialize(account, db=db, today=today)


@router.put("/{username}/proxy", response_model=AccountOut)
def update_account_proxy(
    username: str,
    payload: AccountProxyUpdate,
    db: Session = Depends(get_db),
) -> AccountOut:
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{username}' not found")

    proxy = db.scalar(select(Proxy).where(Proxy.label == payload.proxy_label))
    if proxy is None:
        raise HTTPException(status_code=400, detail=f"Proxy '{payload.proxy_label}' not found")

    account.proxy_id = proxy.id
    db.commit()
    db.refresh(account)

    ensure_fingerprint_and_proxy(account.username, country=proxy.country or "US")

    today = datetime.now(timezone.utc).date().isoformat()
    return _serialize(account, db=db, today=today)


@router.put("/{username}/session", response_model=AccountOut)
def update_account_session(
    username: str,
    payload: AccountSessionUpdate,
    db: Session = Depends(get_db),
) -> AccountOut:
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{username}' not found")

    account.session_id = payload.session_id.strip()
    clear_session_file(account.username)
    db.commit()
    db.refresh(account)

    today = datetime.now(timezone.utc).date().isoformat()
    return _serialize(account, db=db, today=today)


@router.get("/{username}/session", response_model=AccountSessionOut)
def get_account_session(username: str, db: Session = Depends(get_db)) -> AccountSessionOut:
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{username}' not found")

    exported = export_sessionid(username, db_session_id=account.session_id)
    if exported is None:
        raise HTTPException(
            status_code=404,
            detail="No session found — import a sessionid or log in first",
        )
    return AccountSessionOut(
        session_id=exported.session_id,
        source=exported.source,
        session_file_exists=exported.session_file_exists,
    )


def _set_status(db: Session, username: str, new_status: AccountStatus) -> AccountOut:
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{username}' not found")
    account.status = new_status
    db.commit()
    db.refresh(account)
    today = datetime.now(timezone.utc).date().isoformat()
    return _serialize(account, db=db, today=today)


@router.post("/{username}/pause", response_model=AccountOut)
def pause_account(username: str, db: Session = Depends(get_db)) -> AccountOut:
    return _set_status(db, username, AccountStatus.paused)


@router.post("/{username}/resume", response_model=AccountOut)
def resume_account(username: str, db: Session = Depends(get_db)) -> AccountOut:
    return _set_status(db, username, AccountStatus.active)


@router.post("/{username}/test-connection", response_model=AccountConnectionTestOut)
def test_account_connection(username: str, db: Session = Depends(get_db)) -> AccountConnectionTestOut:
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{username}' not found")
    return run_account_connection_test(account, db)


@router.post("/{username}/first-login", response_model=FirstLoginOut)
def account_first_login(username: str, db: Session = Depends(get_db)) -> FirstLoginOut:
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{username}' not found")
    from app.behavior.warmup_playwright import playwright_browsers_available

    if not playwright_browsers_available():
        raise HTTPException(
            status_code=503,
            detail="Chromium не установлен — выполните install-playwright на сервере",
        )
    return run_account_first_login(account, db)
