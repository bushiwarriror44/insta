"""In-memory interactive Playwright browser sessions streamed via noVNC."""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from app.accounts.backup_codes import consume_next_backup_code
from app.accounts.device_factory import load_fingerprint
from app.accounts.login_identifier import resolve_login_identifier
from app.accounts.playwright_session import (
    import_playwright_session_to_account,
    playwright_state_path,
    sessionid_from_playwright_state_data,
    storage_state_has_session,
)
from app.behavior.warmup_playwright import (
    _INSTAGRAM_LOGIN_URL,
    _INSTAGRAM_URL,
    _accept_cookie_banner,
    _apply_stealth_context,
    _detect_2fa_required,
    _detect_challenge,
    _dismiss_post_login_modals,
    _ensure_login_page,
    _fill_login_field,
    _has_auth_cookies,
    _human_wait,
    _is_logged_in,
    _login_form_visible,
    _parse_proxy,
    _submit_login_form,
    _try_submit_totp,
    playwright_browsers_available,
    submit_verification_code,
)
from app.behavior.playwright_surface import (
    LoginSurface,
    browser_launch_args,
    playwright_context_kwargs,
    resolve_playwright_surface,
    vnc_screen_size,
)
from app.browser.vnc_stack import VncStack, allocate_ports, vnc_stack_available
from app.config import settings
from app.geo.timezone_normalize import normalize_playwright_timezone
from app.logging_setup import get_logger

logger = get_logger(__name__)

_GOTO_WARNING_MESSAGE = (
    "Instagram не открылся через прокси (HTTP-ошибка). "
    "Введите instagram.com вручную в браузере или смените прокси/режим на Десктоп."
)

def _is_on_instagram(url: str | None) -> bool:
    return bool(url and "instagram.com" in url)


def _goto_warning_message(http_status: int | None) -> str:
    if http_status is not None:
        return (
            f"Страница логина вернула HTTP {http_status} через прокси. {_GOTO_WARNING_MESSAGE}"
        )
    return _GOTO_WARNING_MESSAGE


async def _try_goto_url(
    page,
    url: str,
    *,
    username: str,
    nav_status: dict[str, Any],
) -> bool:
    """Navigate to ``url``; return True when the page landed on Instagram."""
    last_exc: Exception | None = None
    goto_timeout = settings.browser_goto_timeout_sec * 1000

    def on_response(response) -> None:
        try:
            request = response.request
            if request.is_navigation_request() and request.frame == page.main_frame:
                nav_status["http_status"] = response.status
                nav_status["url"] = response.url
        except Exception:
            pass

    page.on("response", on_response)
    try:
        try:
            await page.goto(url, wait_until="commit", timeout=goto_timeout)
            logger.info(
                "browser_session.goto_ok",
                username=username,
                url=url,
                wait_until="commit",
                http_status=nav_status.get("http_status"),
            )
            return True
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "browser_session.goto_attempt_failed",
                username=username,
                url=url,
                wait_until="commit",
                http_status=nav_status.get("http_status"),
                error=str(exc),
            )
            if _is_on_instagram(page.url):
                return True
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=goto_timeout)
            logger.info(
                "browser_session.goto_ok",
                username=username,
                url=url,
                wait_until="domcontentloaded",
                http_status=nav_status.get("http_status"),
            )
            return True
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "browser_session.goto_attempt_failed",
                username=username,
                url=url,
                wait_until="domcontentloaded",
                http_status=nav_status.get("http_status"),
                error=str(exc),
            )
            if _is_on_instagram(page.url):
                return True
        if last_exc is not None:
            logger.warning(
                "browser_session.goto_failed",
                username=username,
                url=url,
                http_status=nav_status.get("http_status"),
                error=str(last_exc),
            )
        return _is_on_instagram(page.url)
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass


async def _open_instagram_browser(page, *, username: str, need_login: bool) -> str | None:
    """Open Instagram via a URL ladder; never fall back to about:blank."""
    urls = [_INSTAGRAM_URL]
    if need_login and not await _login_form_visible(page):
        urls.append(_INSTAGRAM_LOGIN_URL)

    nav_status: dict[str, Any] = {}
    last_http_status: int | None = None
    on_ig = False

    for url in urls:
        nav_status.clear()
        landed = await _try_goto_url(page, url, username=username, nav_status=nav_status)
        last_http_status = nav_status.get("http_status")
        if landed or _is_on_instagram(page.url):
            on_ig = True
            if not need_login or url == _INSTAGRAM_LOGIN_URL:
                return None
            if await _login_form_visible(page):
                return None

    if on_ig:
        return None
    return _goto_warning_message(last_http_status)


class BrowserSessionStatus(str, Enum):
    starting = "starting"
    running = "running"
    awaiting_code = "awaiting_code"
    saved = "saved"
    error = "error"
    stopped = "stopped"


@dataclass
class BrowserSessionState:
    username: str
    status: BrowserSessionStatus = BrowserSessionStatus.starting
    awaiting_code: bool = False
    error: str | None = None
    launch_warning: str | None = None
    proxy_label: str | None = None
    proxy_ip: str | None = None
    proxy_geo_country: str | None = None
    proxy_country: str | None = None
    proxy_timezone: str | None = None
    proxy_instagram_reachable: bool | None = None
    proxy_instagram_login_reachable: bool | None = None
    display: int = 0
    ws_port: int = 0
    vnc_path: str = ""
    page_url: str | None = None
    login_surface: LoginSurface = "mobile"
    started_at: float = field(default_factory=time.monotonic)
    vnc_stack: VncStack | None = None
    pw: Any = None
    browser: Any = None
    context: Any = None
    page: Any = None
    poll_task: asyncio.Task | None = None
    auto_stop_task: asyncio.Task | None = None


class BrowserSessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, BrowserSessionState] = {}
        self._lock = asyncio.Lock()
        self._display_counter = settings.browser_display_base

    def _next_display(self) -> int:
        self._display_counter += 1
        if self._display_counter > 180:
            self._display_counter = settings.browser_display_base + 1
        return self._display_counter

    def get(self, username: str) -> BrowserSessionState | None:
        return self._sessions.get(username)

    def apply_proxy_snapshot(self, username: str, snapshot: Any) -> None:
        session = self._sessions.get(username)
        if session is None or snapshot is None:
            return
        if getattr(snapshot, "ip", None):
            session.proxy_ip = snapshot.ip
        if getattr(snapshot, "country", None):
            session.proxy_geo_country = snapshot.country
        session.proxy_instagram_reachable = getattr(snapshot, "instagram_reachable", None)
        session.proxy_instagram_login_reachable = getattr(
            snapshot, "instagram_login_reachable", None
        )

    def status_dict(self, username: str) -> dict[str, Any]:
        session = self._sessions.get(username)
        if session is None:
            return {
                "username": username,
                "status": BrowserSessionStatus.stopped.value,
                "awaiting_code": False,
                "vnc_path": None,
                "page_url": None,
                "error": None,
                "login_surface": None,
                "warning": None,
                "proxy_label": None,
                "proxy_ip": None,
                "proxy_geo_country": None,
                "proxy_country": None,
                "proxy_timezone": None,
                "proxy_instagram_reachable": None,
                "proxy_instagram_login_reachable": None,
            }
        return {
            "username": username,
            "status": session.status.value,
            "awaiting_code": session.awaiting_code,
            "vnc_path": session.vnc_path or None,
            "page_url": session.page_url,
            "error": session.error,
            "login_surface": session.login_surface,
            "warning": session.launch_warning,
            "proxy_label": session.proxy_label,
            "proxy_ip": session.proxy_ip,
            "proxy_geo_country": session.proxy_geo_country,
            "proxy_country": session.proxy_country,
            "proxy_timezone": session.proxy_timezone,
            "proxy_instagram_reachable": session.proxy_instagram_reachable,
            "proxy_instagram_login_reachable": session.proxy_instagram_login_reachable,
        }

    async def start_session(
        self,
        account,
        proxy,
        *,
        autofill_login: bool = True,
        surface: LoginSurface | str | None = None,
        proxy_snapshot: Any = None,
    ) -> BrowserSessionState:
        username = account.username
        resolved_surface = resolve_playwright_surface(surface or getattr(account, "login_surface", None))
        async with self._lock:
            existing = self._sessions.get(username)
            if existing and existing.status not in (
                BrowserSessionStatus.stopped,
                BrowserSessionStatus.error,
                BrowserSessionStatus.saved,
            ):
                return existing

            if existing:
                await self._cleanup_session(existing, remove=False)

            if not settings.browser_vnc_enabled:
                raise RuntimeError("Interactive browser disabled (set BROWSER_VNC_ENABLED=true)")
            if not vnc_stack_available():
                raise RuntimeError("Xvfb/x11vnc/websockify not installed on server")
            if not playwright_browsers_available():
                raise RuntimeError("Chromium not installed — run install-playwright on server")

            display = self._next_display()
            rfb_port, ws_port = allocate_ports(display)
            lightweight = settings.browser_lightweight
            vnc = VncStack(
                display=display,
                rfb_port=rfb_port,
                ws_port=ws_port,
                screen=vnc_screen_size(resolved_surface, lightweight=lightweight),
                lightweight=lightweight,
            )
            session = BrowserSessionState(
                username=username,
                display=display,
                ws_port=ws_port,
                vnc_path=f"/api/accounts/{username}/browser/vnc/ws",
                vnc_stack=vnc,
                login_surface=resolved_surface,
                proxy_label=getattr(proxy, "label", None),
                proxy_country=getattr(proxy, "country", None),
                proxy_timezone=normalize_playwright_timezone(
                    getattr(proxy, "timezone", None),
                    country=getattr(proxy, "country", None),
                ),
                proxy_ip=(
                    getattr(proxy_snapshot, "ip", None)
                    or getattr(proxy, "last_known_ip", None)
                ),
                proxy_geo_country=(
                    getattr(proxy_snapshot, "country", None)
                    or getattr(proxy, "last_geo_country", None)
                ),
                proxy_instagram_reachable=getattr(proxy_snapshot, "instagram_reachable", None),
                proxy_instagram_login_reachable=getattr(
                    proxy_snapshot, "instagram_login_reachable", None
                ),
            )
            self._sessions[username] = session

        try:
            await vnc.start()
            await self._launch_browser(
                session,
                account,
                proxy,
                autofill_login=autofill_login,
                surface=resolved_surface,
            )
            session.status = BrowserSessionStatus.running
            session.poll_task = asyncio.create_task(self._poll_session(session, account))
            timeout_sec = settings.browser_session_timeout_min * 60
            session.auto_stop_task = asyncio.create_task(self._auto_stop(username, timeout_sec))
            return session
        except Exception as exc:
            session.status = BrowserSessionStatus.error
            session.error = str(exc)
            logger.error("browser_session.start_failed", username=username, error=str(exc))
            await self._cleanup_session(session)
            raise

    async def _launch_browser(
        self,
        session: BrowserSessionState,
        account,
        proxy,
        *,
        autofill_login: bool,
        surface: LoginSurface,
    ) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("playwright not installed") from exc

        stealth_apply = None
        try:
            from playwright_stealth import stealth_async  # type: ignore

            stealth_apply = stealth_async
        except ImportError:
            try:
                from playwright_stealth import Stealth  # type: ignore

                stealth_instance = Stealth()

                async def _apply(page):
                    await stealth_instance.apply_stealth_async(page)

                stealth_apply = _apply
            except ImportError:
                pass

        fingerprint = load_fingerprint(account.username)
        locale = getattr(fingerprint, "locale", None) or "en-US"
        tz_id = normalize_playwright_timezone(proxy.timezone, country=proxy.country)

        proxy_arg = _parse_proxy(proxy.url)
        if not proxy_arg:
            raise RuntimeError("proxy required for interactive browser")

        state_file = playwright_state_path(account.username)
        display_env = os.environ.copy()
        display_env["DISPLAY"] = vnc_stack_display(session)
        lightweight = settings.browser_lightweight

        session.pw = await async_playwright().start()
        session.browser = await session.pw.chromium.launch(
            headless=False,
            ignore_default_args=["--enable-automation"],
            args=browser_launch_args(surface, lightweight=lightweight),
            proxy=proxy_arg,
            env=display_env,
        )

        context_kwargs = playwright_context_kwargs(
            surface,
            fingerprint=fingerprint,
            locale=locale,
            timezone_id=tz_id,
            storage_state_path=str(state_file)
            if state_file.exists() and storage_state_has_session(account.username)
            else None,
            lightweight=lightweight,
        )

        session.context = await session.browser.new_context(**context_kwargs)
        await _apply_stealth_context(session.context, surface)
        session.page = await session.context.new_page()
        if stealth_apply is not None:
            try:
                await stealth_apply(session.page)
            except Exception:
                pass

        page = session.page
        has_saved_session = state_file.exists() and storage_state_has_session(account.username)
        warning = await _open_instagram_browser(
            page,
            username=account.username,
            need_login=not has_saved_session,
        )
        if warning:
            session.launch_warning = warning

        await _human_wait(0.2, 0.5)
        on_ig = _is_on_instagram(page.url)
        if on_ig or not session.launch_warning:
            await _accept_cookie_banner(page)
        session.page_url = page.url

        if (
            autofill_login
            and not await _is_logged_in(session.context, page)
            and (on_ig or not session.launch_warning)
        ):
            login_id = resolve_login_identifier(account)
            try:
                await _ensure_login_page(page, fast=True)
                await _fill_login_field(page, password=False, text=login_id)
                await _human_wait(0.2, 0.5)
                await _fill_login_field(page, password=True, text=account.password)
                await _submit_login_form(page)
                await _human_wait(0.5, 1.0)
                await _try_submit_totp(page, account.totp_seed)
                await _dismiss_post_login_modals(page)
            except Exception as exc:
                logger.warning("browser_session.autofill_failed", username=account.username, error=str(exc))

        session.page_url = page.url
        await self._refresh_code_state(session)

    async def _poll_session(self, session: BrowserSessionState, account) -> None:
        while session.status in (BrowserSessionStatus.running, BrowserSessionStatus.awaiting_code):
            try:
                if session.page is None or session.context is None:
                    break
                if await _is_logged_in(session.context, session.page):
                    session.awaiting_code = False
                    if session.status == BrowserSessionStatus.awaiting_code:
                        session.status = BrowserSessionStatus.running
                else:
                    await self._refresh_code_state(session)
                session.page_url = session.page.url
            except Exception as exc:
                logger.warning("browser_session.poll_error", username=session.username, error=str(exc))
            await asyncio.sleep(2.0)

    async def _refresh_code_state(self, session: BrowserSessionState) -> None:
        if session.page is None:
            return
        needs_code = await _detect_2fa_required(session.page) or await _detect_challenge(session.page)
        session.awaiting_code = needs_code
        if needs_code and session.status == BrowserSessionStatus.running:
            session.status = BrowserSessionStatus.awaiting_code

    async def submit_code(self, db: Session, account, code: str | None) -> bool:
        session = self._sessions.get(account.username)
        if session is None or session.page is None:
            raise RuntimeError("No active browser session for this account")

        resolved = (code or "").strip()
        if not resolved:
            resolved = consume_next_backup_code(db, account) or ""
        if not resolved:
            raise ValueError("Verification code is required")

        ok = await submit_verification_code(session.page, resolved)
        if not ok:
            raise RuntimeError("Could not find a verification code field on the page")

        await _human_wait(2.0, 4.0)
        await _dismiss_post_login_modals(session.page)
        await self._refresh_code_state(session)
        session.page_url = session.page.url
        if await _is_logged_in(session.context, session.page):
            session.status = BrowserSessionStatus.running
            session.awaiting_code = False
        return ok

    async def save_session(self, db: Session, account) -> dict[str, Any]:
        session = self._sessions.get(account.username)
        if session is None or session.context is None:
            raise RuntimeError("No active browser session for this account")

        if session.page is None or not await _is_logged_in(session.context, session.page):
            raise RuntimeError(
                "Сначала войдите в Instagram в браузере — sessionid не найден в cookies"
            )

        state_file = playwright_state_path(account.username)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        await session.context.storage_state(path=str(state_file))
        data = json.loads(state_file.read_text(encoding="utf-8"))
        session_id = sessionid_from_playwright_state_data(data)
        imported = import_playwright_session_to_account(db, account, session_id=session_id)
        if not imported:
            raise RuntimeError("Could not extract sessionid from browser state")

        session.status = BrowserSessionStatus.saved
        session.awaiting_code = False
        return {
            "session_imported": True,
            "session_id_saved": bool(session_id),
        }

    async def stop_session(self, username: str) -> None:
        async with self._lock:
            session = self._sessions.get(username)
            if session is None:
                return
            await self._cleanup_session(session)
            session.status = BrowserSessionStatus.stopped

    async def _auto_stop(self, username: str, timeout_sec: float) -> None:
        await asyncio.sleep(timeout_sec)
        session = self._sessions.get(username)
        if session is None:
            return
        if session.status in (BrowserSessionStatus.stopped, BrowserSessionStatus.saved):
            return
        logger.info("browser_session.auto_stop", username=username, timeout_sec=timeout_sec)
        await self.stop_session(username)

    async def _cleanup_session(self, session: BrowserSessionState, *, remove: bool = True) -> None:
        for task in (session.poll_task, session.auto_stop_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        if session.page is not None:
            try:
                await session.page.close()
            except Exception:
                pass
        if session.context is not None:
            try:
                await session.context.close()
            except Exception:
                pass
        if session.browser is not None:
            try:
                await session.browser.close()
            except Exception:
                pass
        if session.pw is not None:
            try:
                await session.pw.stop()
            except Exception:
                pass
        if session.vnc_stack is not None:
            session.vnc_stack.stop()

        session.page = None
        session.context = None
        session.browser = None
        session.pw = None
        session.vnc_stack = None

        if remove:
            self._sessions.pop(session.username, None)


def vnc_stack_display(session: BrowserSessionState) -> str:
    return f":{session.display}"


browser_session_manager = BrowserSessionManager()
