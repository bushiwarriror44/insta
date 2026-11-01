"""YouTube / TikTok Studio login: headless Playwright + optional VNC fallback."""
from __future__ import annotations

import asyncio
import time
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.account_diagnostics import log_account_credentials, proxy_log_line
from app.accounts.connection_ladder import (
    METHOD_REUSE,
    METHOD_STUDIO_HEADLESS,
    METHOD_VNC,
    ConnectionLadder,
)
from app.accounts.cookie_formats import studio_session_ready
from app.accounts.login_identifier import resolve_login_identifier
from app.accounts.playwright_session import clear_studio_playwright_state
from app.api.schemas import DiagnosticLogLineOut, FirstLoginOut
from app.behavior.studio_playwright import studio_login
from app.behavior.warmup_playwright import playwright_browsers_available
from app.browser.vnc_stack import vnc_stack_available
from app.config import settings
from app.db import Account, DiagnosticRunKind, Platform, Proxy
from app.diagnostics.collector import DiagnosticCollector

StatusCallback = Callable[[str, Optional[str]], None]

PLAYWRIGHT_UNAVAILABLE = "Chromium не установлен — выполните install-playwright на сервере"
VNC_POLL_TIMEOUT_SEC = 600
VNC_POLL_INTERVAL_SEC = 3.0
AWAIT_CODE_GRACE_SEC = 120


def _platform_value(account: Account) -> str:
    platform = getattr(account, "platform", None)
    if platform is None:
        return "instagram"
    return getattr(platform, "value", platform) or "instagram"


def resolve_studio_login_identifier(account: Account) -> str:
    email = (account.email or "").strip()
    if email:
        return email
    return resolve_login_identifier(account)


def _finish(
    collector: DiagnosticCollector,
    *,
    ok: bool,
    summary: str,
    status: str,
    challenge: bool = False,
    browser_tab_hint: bool = False,
    session_imported: bool = False,
    error: str | None = None,
) -> FirstLoginOut:
    collector.finish(status, summary)
    return FirstLoginOut(
        run_id=collector.run_id,
        ok=ok,
        challenge=challenge,
        browser_tab_hint=browser_tab_hint,
        session_imported=session_imported,
        error=error,
        logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
    )


def _run_vnc_fallback(
    collector: DiagnosticCollector,
    account: Account,
    db: Session,
    proxy: Proxy,
    *,
    on_status: StatusCallback | None = None,
    ladder: ConnectionLadder | None = None,
) -> FirstLoginOut:
    from app.browser.session_manager import BrowserSessionStatus, browser_session_manager

    if ladder is not None:
        ladder.start(METHOD_VNC, "интерактивный браузер")
    if not settings.browser_vnc_enabled:
        if ladder is not None:
            ladder.fail(METHOD_VNC, error="BROWSER_VNC_ENABLED выключен")
        return _finish(
            collector,
            ok=False,
            summary="Требуется подтверждение — включите BROWSER_VNC_ENABLED",
            status="warn",
            challenge=True,
            browser_tab_hint=True,
            error="Интерактивный браузер отключён на сервере",
        )
    if not vnc_stack_available():
        if ladder is not None:
            ladder.fail(METHOD_VNC, error="VNC стек недоступен")
        return _finish(
            collector,
            ok=False,
            summary="Требуется подтверждение — VNC стек недоступен",
            status="warn",
            challenge=True,
            browser_tab_hint=True,
            error="Xvfb/x11vnc/websockify не установлены",
        )

    platform = _platform_value(account)
    if on_status:
        on_status("Браузер", f"VNC для {platform}")

    async def _orchestrate() -> tuple[bool, bool, str | None]:
        await browser_session_manager.start_session(
            account,
            proxy,
            autofill_login=True,
            surface="desktop",
            proxy_snapshot=None,
        )
        browser_session_manager.set_login_orchestration(account.username, True)
        deadline = time.monotonic() + VNC_POLL_TIMEOUT_SEC
        last_log_idx = 0
        awaiting_since: float | None = None
        while time.monotonic() < deadline:
            session = browser_session_manager._sessions.get(account.username)
            if session is not None:
                logs = session.action_logs or []
                while last_log_idx < len(logs):
                    item = logs[last_log_idx]
                    last_log_idx += 1
                    msg = str(item.get("message") or "")
                    step = str(item.get("step") or "browser")
                    if on_status and msg:
                        on_status(step, msg[:200])
            status = browser_session_manager.status_dict(account.username)
            st = status.get("status")
            if st == BrowserSessionStatus.awaiting_code.value:
                if awaiting_since is None:
                    awaiting_since = time.monotonic()
                    if on_status:
                        on_status("2FA", "ожидаю код (submit_login_code)")
                elif time.monotonic() - awaiting_since >= AWAIT_CODE_GRACE_SEC:
                    return (
                        False,
                        True,
                        "Введите код 2FA (submit_login_code или вкладка «Браузер»)",
                    )
            if st == BrowserSessionStatus.saved.value:
                return True, False, None
            if studio_session_ready(account.username, platform):
                try:
                    await browser_session_manager.save_session(db, account)
                except RuntimeError:
                    pass
                if studio_session_ready(account.username, platform):
                    return True, False, None
            await asyncio.sleep(VNC_POLL_INTERVAL_SEC)
        return False, True, "Таймаут ожидания входа в браузере"

    try:
        ok, challenge, err = asyncio.run(_orchestrate())
    except Exception as exc:  # noqa: BLE001
        if ladder is not None:
            ladder.fail(METHOD_VNC, error=str(exc))
        collector.error("browser", f"VNC fallback: {exc}")
        return _finish(
            collector,
            ok=False,
            summary=str(exc),
            status="fail",
            challenge=True,
            browser_tab_hint=True,
            error=str(exc),
        )

    if ok:
        if ladder is not None:
            ladder.ok(METHOD_VNC, "Studio cookies сохранены")
        collector.info("session", "Playwright state Studio сохранён")
        return _finish(
            collector,
            ok=True,
            summary=ladder.summary_ok() if ladder is not None else "Studio-сессия сохранена",
            status="ok",
            session_imported=True,
        )
    if ladder is not None:
        ladder.fail(METHOD_VNC, error=err or "challenge")
    return _finish(
        collector,
        ok=False,
        summary=err or "Требуется подтверждение",
        status="warn",
        challenge=challenge,
        browser_tab_hint=True,
        error=err,
    )


def run_studio_login(
    account: Account,
    db: Session,
    *,
    on_status: StatusCallback | None = None,
    allow_vnc_fallback: bool = True,
) -> FirstLoginOut:
    collector = DiagnosticCollector(
        db,
        kind=DiagnosticRunKind.studio_login,
        account_id=account.id,
    )
    ladder = ConnectionLadder(collector)
    platform = _platform_value(account)
    if platform not in ("youtube", "tiktok"):
        collector.error("platform", "studio_login только для YouTube и TikTok")
        return _finish(
            collector,
            ok=False,
            summary="Неверная платформа",
            status="fail",
            error="Неверная платформа",
        )

    if not playwright_browsers_available():
        collector.error("browser", PLAYWRIGHT_UNAVAILABLE)
        return _finish(
            collector,
            ok=False,
            summary=PLAYWRIGHT_UNAVAILABLE,
            status="fail",
            error=PLAYWRIGHT_UNAVAILABLE,
        )

    if not account.proxy_id:
        collector.error("proxy", "Прокси не назначен")
        return _finish(collector, ok=False, summary="Прокси не назначен", status="fail", error="Прокси не назначен")

    proxy = db.get(Proxy, account.proxy_id)
    if proxy is None:
        collector.error("proxy", "Запись прокси отсутствует")
        return _finish(
            collector,
            ok=False,
            summary="Запись прокси отсутствует",
            status="fail",
            error="Запись прокси отсутствует",
        )

    if studio_session_ready(account.username, platform):
        ladder.start(METHOD_REUSE, "Studio cookies на диске")
        ladder.ok(METHOD_REUSE, "повторный вход не нужен")
        collector.info("session", "Studio cookies уже есть — повторный вход не нужен")
        return _finish(
            collector,
            ok=True,
            summary=ladder.summary_ok(),
            status="ok",
            session_imported=True,
        )

    log_account_credentials(collector, account, proxy)
    login_id = resolve_studio_login_identifier(account)
    collector.info("start", f"Автовход Studio ({platform}) для @{account.username}")
    collector.info("proxy", proxy_log_line(proxy))

    if on_status:
        on_status("Studio", f"проверяю {platform}")
    if on_status:
        on_status("Headless", "открываю Studio в Chromium")

    password = (account.password or "").strip()
    if not password:
        collector.warn("account", "Пароль не задан — только ручной/VNC вход")
        ladder.skip(METHOD_STUDIO_HEADLESS, "пароль не задан", next_method=METHOD_VNC)
        if on_status:
            on_status("Пароль", "не задан — открою браузер для ручного входа")
        return _run_vnc_fallback(
            collector, account, db, proxy, on_status=on_status, ladder=ladder
        )

    ladder.start(METHOD_STUDIO_HEADLESS, platform, next_method=METHOD_VNC)
    result = studio_login(
        username=account.username,
        password=password,
        proxy_url=proxy.url,
        platform=platform,
        login_identifier=login_id,
        timezone_id=account.timezone or "UTC",
        on_status=on_status,
    )

    if result.ok and studio_session_ready(account.username, platform):
        ladder.ok(METHOD_STUDIO_HEADLESS, "Studio cookies сохранены")
        collector.info("browser", "Headless: Studio cookies сохранены")
        return _finish(
            collector,
            ok=True,
            summary=ladder.summary_ok(),
            status="ok",
            session_imported=True,
        )

    if result.challenge or not result.ok:
        ladder.fail(
            METHOD_STUDIO_HEADLESS,
            error=result.error or "challenge",
            next_method=METHOD_VNC if allow_vnc_fallback else None,
        )
        collector.warn(
            "browser",
            result.error or "Headless: нужно подтверждение или ручной вход",
        )
        if not allow_vnc_fallback:
            return _finish(
                collector,
                ok=False,
                summary=result.error or "Headless: нужно подтверждение или ручной вход",
                status="warn",
                challenge=bool(result.challenge or not result.ok),
                browser_tab_hint=True,
                error=result.error,
            )
        if on_status:
            on_status("Challenge", "перехожу на интерактивный браузер")
        return _run_vnc_fallback(
            collector, account, db, proxy, on_status=on_status, ladder=ladder
        )

    ladder.fail(METHOD_STUDIO_HEADLESS, error=result.error or "нет cookies")
    collector.error("browser", result.error or "Не удалось сохранить Studio-сессию")
    return _finish(
        collector,
        ok=False,
        summary=ladder.summary_fail(result.error),
        status="fail",
        error=result.error,
    )


def list_studio_accounts(
    db: Session,
    *,
    imported_only: bool = False,
    username: str | None = None,
) -> list[Account]:
    q = select(Account).where(Account.platform.in_([Platform.youtube, Platform.tiktok]))
    if username:
        q = q.where(Account.username == username)
    accounts = list(db.scalars(q.order_by(Account.platform, Account.username)))
    if imported_only:
        mobile_ids = {
            p.id for p in db.scalars(select(Proxy).where(Proxy.label.like("am-mobile-%")))
        }
        accounts = [a for a in accounts if a.proxy_id in mobile_ids]
    return accounts


def run_studio_login_batch(
    db: Session,
    accounts: list[Account],
    *,
    force: bool = False,
    allow_vnc_fallback: bool = False,
    on_status: StatusCallback | None = None,
) -> list[dict]:
    rows: list[dict] = []
    for account in accounts:
        platform = _platform_value(account)
        if not (account.password or "").strip():
            rows.append(
                {
                    "username": account.username,
                    "platform": platform,
                    "ok": False,
                    "error": "пароль не задан в БД",
                }
            )
            continue
        if not account.proxy_id:
            rows.append(
                {
                    "username": account.username,
                    "platform": platform,
                    "ok": False,
                    "error": "нет прокси",
                }
            )
            continue
        if force:
            clear_studio_playwright_state(account.username, platform)
        try:
            out = run_studio_login(
                account,
                db,
                on_status=on_status,
                allow_vnc_fallback=allow_vnc_fallback,
            )
            rows.append(
                {
                    "username": account.username,
                    "platform": platform,
                    "ok": out.ok,
                    "challenge": out.challenge,
                    "error": (out.error or "")[:400] or None,
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "username": account.username,
                    "platform": platform,
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}"[:300],
                }
            )
    return rows
