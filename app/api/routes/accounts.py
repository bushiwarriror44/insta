"""Account management endpoints."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.backup_codes import parse_account_line, serialize_backup_codes
from app.accounts.connection_test import run_account_connection_test
from app.accounts.cookie_formats import CookieFormatError, import_cookies_data, write_dolphin_cookies_export
from app.accounts.device_factory import DeviceFingerprint, device_path, load_fingerprint, save_fingerprint
from app.accounts.first_login_service import run_account_first_login
from app.accounts.mint_mobile_session import mint_mobile_session
from app.accounts.playwright_session import (
    clear_playwright_state,
    login_debug_screenshot_path,
    playwright_state_path,
)
from app.accounts.session_export import export_sessionid
from app.accounts.session_cookie import normalize_sessionid
from app.accounts.session_manager import (
    clear_session_file,
    ensure_fingerprint_and_proxy,
    session_path,
)
from app.api.deps import AuthDep, get_db
from app.api.schemas import (
    AccountConnectionTestOut,
    AccountIn,
    AccountNotesUpdate,
    AccountOut,
    AccountProxyUpdate,
    AccountSessionOut,
    AccountSessionUpdate,
    AccountTotpOut,
    CookiesImportOut,
    DeviceFingerprintImportOut,
    FirstLoginOut,
    MintMobileSessionOut,
)
from app.db import Account, AccountStatus, DailyStat, Platform, Proxy
from app.geo.country_codes import normalize_country_code
from app.geo.timezone_normalize import (
    is_placeholder_timezone,
    normalize_playwright_timezone,
    timezone_from_proxy,
)

router = APIRouter(prefix="/api/accounts", tags=["accounts"], dependencies=[AuthDep])


def _account_session_fields(username: str, db_session_id: str | None, platform: str = "instagram"):
    if platform in ("youtube", "tiktok"):
        from app.accounts.cookie_formats import studio_session_ready

        path = playwright_state_path(username)
        file_exists = path.exists()
        updated_at = None
        if file_exists:
            updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        source = "playwright" if studio_session_ready(username, platform) else "none"
        return file_exists, updated_at, source
    path = session_path(username)
    file_exists = path.exists()
    updated_at = None
    if file_exists:
        updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    exported = export_sessionid(username, db_session_id=db_session_id)
    source = exported.source if exported else "none"
    return file_exists, updated_at, source


def _account_local_today(account: Account) -> str:
    """Calendar date_key for DailyStat, matching planner increment_daily_stat."""
    try:
        tz = ZoneInfo(account.timezone)
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date().isoformat()


def _account_platform_value(account: Account) -> str:
    value = getattr(account, "platform", None)
    if hasattr(value, "value"):
        return value.value
    return value or "instagram"


def _serialize(account: Account, *, db: Session) -> AccountOut:
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

    today = _account_local_today(account)
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
        platform=_account_platform_value(account),
    )

    return AccountOut(
        id=account.id,
        username=account.username,
        login_identifier=account.login_identifier,
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
        has_totp=bool((account.totp_seed or "").strip()),
        has_session_id=bool(account.session_id),
        login_surface=account.login_surface if account.login_surface in ("mobile", "desktop") else None,
        session_file_exists=file_exists,
        session_file_updated_at=file_updated_at,
        session_source=session_source,
        posts_today=posts_today,
        failures_today=failures_today,
        notes=account.notes,
        brief=getattr(account, "brief", None) or "",
        hold_for_review=bool(getattr(account, "hold_for_review", False)),
        daily_spend_cap_usd=float(getattr(account, "daily_spend_cap_usd", 0) or 0),
        platform=(
            account.platform.value
            if hasattr(getattr(account, "platform", None), "value")
            else (getattr(account, "platform", None) or "instagram")
        ),
    )


@router.get("", response_model=List[AccountOut])
def list_accounts(db: Session = Depends(get_db)) -> List[AccountOut]:
    rows = db.scalars(select(Account).order_by(Account.username)).all()
    return [_serialize(a, db=db) for a in rows]


@router.post("", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(payload: AccountIn, db: Session = Depends(get_db)) -> AccountOut:
    proxy = db.scalar(select(Proxy).where(Proxy.label == payload.proxy_label))
    if proxy is None:
        raise HTTPException(status_code=400, detail=f"Proxy '{payload.proxy_label}' not found")

    platform = Platform(payload.platform)
    existing = db.scalar(
        select(Account).where(Account.username == payload.username, Account.platform == platform)
    )
    if existing is not None:
        account = existing
    else:
        account = Account(username=payload.username, platform=platform)
        db.add(account)

    account.platform = platform
    account.password = payload.password
    account.proxy_id = proxy.id
    if is_placeholder_timezone(payload.timezone):
        account.timezone = timezone_from_proxy(proxy.timezone, proxy.country)
    else:
        account.timezone = normalize_playwright_timezone(payload.timezone, country=proxy.country)
    account.daily_post_cap = payload.daily_post_cap
    account.min_gap_hours = payload.min_gap_hours
    account.active_hour_start = payload.active_hour_start
    account.active_hour_end = payload.active_hour_end
    if payload.caption_profile is not None:
        account.caption_profile = payload.caption_profile or None
    if payload.totp_seed is not None:
        account.totp_seed = payload.totp_seed.strip() or None
    if payload.session_id is not None:
        if platform is not Platform.instagram:
            raise HTTPException(
                status_code=400,
                detail="session_id только для Instagram — YouTube и TikTok входят через cookies / браузер",
            )
        account.session_id = normalize_sessionid(payload.session_id)
        if account.session_id:
            clear_session_file(account.username)
            clear_playwright_state(account.username)
    if payload.login_identifier is not None:
        account.login_identifier = payload.login_identifier.strip() or None
    if payload.email is not None:
        account.email = payload.email or None
    if payload.email_password is not None:
        account.email_password = payload.email_password or None
    if payload.backup_codes is not None:
        account.backup_codes = payload.backup_codes.strip() or None
    if payload.login_surface is not None:
        from app.behavior.playwright_surface import resolve_playwright_surface

        account.login_surface = resolve_playwright_surface(payload.login_surface)
    if payload.notes is not None:
        account.notes = payload.notes.strip() or None
    if payload.vendor_line:
        from app.accounts.vendor_line import parse_vendor_line

        try:
            parsed = parse_vendor_line(payload.vendor_line)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        account.username = parsed["username"]
        account.password = parsed["password"]
        account.email = parsed["email"]
        account.email_password = parsed["email_password"]
    elif payload.account_line:
        from app.accounts.vendor_line import looks_like_vendor_line, parse_vendor_line

        raw = payload.account_line.strip()
        if looks_like_vendor_line(raw):
            try:
                parsed = parse_vendor_line(raw)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            account.username = parsed["username"]
            account.password = parsed["password"]
            account.email = parsed["email"]
            account.email_password = parsed["email_password"]
        else:
            try:
                parsed = parse_account_line(payload.account_line)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            account.username = parsed["username"]
            account.password = parsed["password"]
            codes = parsed.get("backup_codes") or []
            if codes:
                account.backup_codes = serialize_backup_codes(codes)
    if payload.imap_host is not None:
        account.imap_host = payload.imap_host.strip() or None
    if account.status == AccountStatus.blocked:
        account.status = AccountStatus.active

    db.commit()
    db.refresh(account)

    if _account_platform_value(account) == "instagram":
        ensure_fingerprint_and_proxy(
            account.username,
            country=normalize_country_code(proxy.country) or proxy.country or "US",
            timezone_id=timezone_from_proxy(proxy.timezone, proxy.country),
        )

    return _serialize(account, db=db)


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
    account.timezone = timezone_from_proxy(proxy.timezone, proxy.country)
    db.commit()
    db.refresh(account)

    if _account_platform_value(account) == "instagram":
        ensure_fingerprint_and_proxy(
            account.username,
            country=normalize_country_code(proxy.country) or proxy.country or "US",
            timezone_id=account.timezone,
        )

    return _serialize(account, db=db)


@router.patch("/{username}/notes", response_model=AccountOut)
def update_account_notes(
    username: str,
    payload: AccountNotesUpdate,
    db: Session = Depends(get_db),
) -> AccountOut:
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{username}' not found")

    account.notes = payload.notes.strip() if payload.notes else None
    db.commit()
    db.refresh(account)

    return _serialize(account, db=db)


@router.get("/{username}/totp", response_model=AccountTotpOut)
def get_account_totp(username: str, db: Session = Depends(get_db)) -> AccountTotpOut:
    """Return the stored TOTP seed and the current 6-digit code (admin only)."""
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{username}' not found")

    seed = (account.totp_seed or "").strip()
    if not seed:
        raise HTTPException(status_code=404, detail="TOTP seed не задан для этого аккаунта")

    cleaned = "".join(seed.split()).upper()
    try:
        import pyotp
    except ImportError as exc:  # pragma: no cover
        raise HTTPException(status_code=503, detail="pyotp не установлен") from exc

    try:
        totp = pyotp.TOTP(cleaned)
        code = totp.now()
        # pyotp interval is 30s; remaining until next tick.
        remaining = int(totp.interval - (datetime.now(timezone.utc).timestamp() % totp.interval))
        if remaining <= 0:
            remaining = int(totp.interval)
    except Exception as exc:  # noqa: BLE001 - bad seed
        raise HTTPException(
            status_code=400,
            detail=f"Некорректный TOTP seed: {exc}",
        ) from exc

    return AccountTotpOut(totp_seed=cleaned, code=code, seconds_remaining=remaining)


@router.put("/{username}/session", response_model=AccountOut)
def update_account_session(
    username: str,
    payload: AccountSessionUpdate,
    db: Session = Depends(get_db),
) -> AccountOut:
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{username}' not found")

    if _account_platform_value(account) != "instagram":
        raise HTTPException(
            status_code=400,
            detail="session_id только для Instagram — YouTube и TikTok входят через cookies / браузер",
        )

    normalized = normalize_sessionid(payload.session_id)
    if not normalized:
        raise HTTPException(
            status_code=400,
            detail="Некорректная cookie sessionid (нужно 31+ символов после декодирования)",
        )
    account.session_id = normalized
    clear_session_file(account.username)
    clear_playwright_state(account.username)
    db.commit()
    db.refresh(account)

    return _serialize(account, db=db)


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


@router.get("/{username}/cookies/export")
def export_account_cookies(
    username: str,
    format: str = Query(default="json"),
    db: Session = Depends(get_db),
) -> FileResponse:
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{username}' not found")
    as_txt = (format or "json").strip().lower() == "txt"
    try:
        export_path = write_dolphin_cookies_export(
            username,
            db_session_id=account.session_id,
            as_txt=as_txt,
            platform=_account_platform_value(account),
        )
    except CookieFormatError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path=export_path,
        media_type="text/plain" if as_txt else "application/json",
        filename=f"cookies_{username}.txt" if as_txt else f"cookies_{username}.json",
    )


@router.get("/{username}/login-debug-screenshot")
def export_login_debug_screenshot(username: str, db: Session = Depends(get_db)) -> FileResponse:
    """Return the latest Playwright login failure screenshot for diagnostics."""
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{username}' not found")
    path = login_debug_screenshot_path(username)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Скриншот не найден — выполните автовход с ошибкой",
        )
    return FileResponse(
        path=path,
        media_type="image/png",
        filename=f"login_debug_{username}.png",
    )


@router.get("/{username}/playwright-state")
def export_playwright_state(
    username: str,
    format: str = Query(default="json"),
    db: Session = Depends(get_db),
) -> FileResponse:
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{username}' not found")
    path = playwright_state_path(username)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Playwright state.json не найден — импортируйте cookies или сохраните сессию в браузере",
        )
    as_txt = (format or "json").strip().lower() == "txt"
    return FileResponse(
        path=path,
        media_type="text/plain" if as_txt else "application/json",
        filename=f"state_{username}.txt" if as_txt else f"state_{username}.json",
    )


@router.get("/{username}/device-fingerprint")
def export_device_fingerprint(
    username: str,
    format: str = Query(default="json"),
    db: Session = Depends(get_db),
) -> FileResponse:
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{username}' not found")
    path = device_path(username)
    if not path.exists():
        fp = load_fingerprint(username)
        if fp is None:
            raise HTTPException(
                status_code=404,
                detail="Device fingerprint не найден для этого аккаунта",
            )
    as_txt = (format or "json").strip().lower() == "txt"
    return FileResponse(
        path=path,
        media_type="text/plain" if as_txt else "application/json",
        filename=f"device_{username}.txt" if as_txt else f"device_{username}.json",
    )


@router.post("/{username}/device-fingerprint", response_model=DeviceFingerprintImportOut)
async def import_device_fingerprint(
    username: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> DeviceFingerprintImportOut:
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{username}' not found")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Файл пуст")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Некорректный JSON") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="ожидается JSON-объект fingerprint")
    try:
        fp = DeviceFingerprint.from_dict(data)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"некорректный fingerprint: {exc}") from exc
    save_fingerprint(username, fp)
    return DeviceFingerprintImportOut(username=username, saved=True)


@router.post("/{username}/cookies/import", response_model=CookiesImportOut)
async def import_account_cookies(
    username: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> CookiesImportOut:
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{username}' not found")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Файл пуст")

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Некорректный JSON") from exc

    try:
        result = import_cookies_data(username, data, platform=_account_platform_value(account))
    except CookieFormatError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if result.session_id:
        account.session_id = result.session_id
    db.commit()

    return CookiesImportOut(
        format=result.format,
        session_id=result.session_id,
        session_id_imported=bool(result.session_id),
        playwright_state_saved=result.playwright_state_saved,
        session_file_cleared=result.session_file_cleared,
    )


def _set_status(db: Session, username: str, new_status: AccountStatus) -> AccountOut:
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{username}' not found")
    account.status = new_status
    db.commit()
    db.refresh(account)
    return _serialize(account, db=db)


@router.post("/{username}/pause", response_model=AccountOut)
def pause_account(username: str, db: Session = Depends(get_db)) -> AccountOut:
    return _set_status(db, username, AccountStatus.paused)


@router.post("/{username}/resume", response_model=AccountOut)
def resume_account(username: str, db: Session = Depends(get_db)) -> AccountOut:
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{username}' not found")
    account.cooldown_until = None
    account.status = AccountStatus.active
    db.commit()
    db.refresh(account)
    return _serialize(account, db=db)


@router.post("/{username}/test-connection", response_model=AccountConnectionTestOut)
def test_account_connection(
    username: str,
    probe_mobile: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> AccountConnectionTestOut:
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{username}' not found")
    return run_account_connection_test(account, db, probe_mobile=probe_mobile)


@router.post("/{username}/first-login", response_model=FirstLoginOut)
def account_first_login(
    username: str,
    login_surface: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> FirstLoginOut:
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{username}' not found")
    from app.behavior.warmup_playwright import playwright_browsers_available

    if not playwright_browsers_available():
        raise HTTPException(
            status_code=503,
            detail="Chromium не установлен — выполните install-playwright на сервере",
        )
    platform = _account_platform_value(account)
    if platform in ("youtube", "tiktok"):
        from app.accounts.studio_login_service import run_studio_login

        return run_studio_login(account, db)
    return run_account_first_login(account, db, surface=login_surface)


@router.post("/{username}/mint-mobile-session", response_model=MintMobileSessionOut)
def account_mint_mobile_session(
    username: str, db: Session = Depends(get_db)
) -> MintMobileSessionOut:
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{username}' not found")
    if _account_platform_value(account) != "instagram":
        raise HTTPException(
            status_code=400,
            detail="mint_mobile_session только для Instagram",
        )
    return mint_mobile_session(account, db)
