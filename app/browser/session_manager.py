"""In-memory interactive Playwright browser sessions streamed via noVNC."""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

import httpx
from sqlalchemy.orm import Session

from app.accounts.backup_codes import consume_next_backup_code
from app.accounts.device_factory import load_fingerprint
from app.accounts.login_identifier import resolve_login_identifier
from app.accounts.cookie_formats import cookies_match_platform
from app.accounts.playwright_session import (
    import_playwright_session_to_account,
    playwright_state_path,
    playwright_state_write_path,
    sessionid_from_playwright_state_data,
    storage_state_has_session,
)
from app.accounts.device_factory import ensure_playwright_chrome_major
from app.accounts.studio_desktop_profile import (
    desktop_playwright_context_kwargs,
    ensure_desktop_playwright_profile,
    ensure_studio_desktop_profile,
    studio_playwright_context_kwargs,
)
from app.accounts.session_cookie import sessionid_diag_label
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
    _human_wait,
    _is_logged_in,
    _login_form_visible,
    _parse_proxy,
    _submit_login_form,
    _try_submit_totp,
    playwright_browsers_available,
    submit_verification_code,
)
from app.behavior.playwright_channel import chromium_launch_channel_kwargs, normalize_playwright_channel
from app.behavior.playwright_surface import (
    LoginSurface,
    browser_launch_args,
    playwright_context_kwargs,
    resolve_playwright_surface,
    studio_vnc_launch_args,
    vnc_screen_size,
)
from app.browser.vnc_stack import VncStack, allocate_ports, vnc_stack_available
from app.diagnostics.collector import DiagnosticCollector
from app.db.models import DiagnosticRunKind
from app.proxies.pool import HealthCheckScope, ProxyError, health_check_cached, note_proxy_login_http_status
from app.config import settings
from app.geo.timezone_normalize import normalize_playwright_timezone
from app.logging_setup import get_logger

logger = get_logger(__name__)

_MAX_ACTION_LOGS = 200
LogLevel = Literal["info", "warn", "error"]
NavTarget = Literal[
    "auto",
    "login",
    "home",
    "reels",
    "explore",
    "direct",
    "activity",
    "profile",
    "edit_profile",
]

_INSTAGRAM_BASE = "https://www.instagram.com"


def _account_platform_value(account) -> str:
    platform = getattr(account, "platform", None)
    if isinstance(platform, str) and platform.strip():
        return platform
    value = getattr(platform, "value", None) if platform is not None else None
    if isinstance(value, str) and value.strip():
        return value
    return "instagram"


def _studio_desktop_geometry(platform_value: str) -> tuple[int, int] | None:
    if platform_value in ("youtube", "tiktok"):
        return (settings.browser_studio_vnc_width, settings.browser_studio_vnc_height)
    return None


async def _platform_logged_in(context, page, platform: str) -> bool:
    if platform == "instagram":
        return await _is_logged_in(context, page)
    cookies = await context.cookies()
    return cookies_match_platform(cookies, platform)


def _nav_urls_for_target(
    target: NavTarget,
    *,
    username: str,
    need_login: bool,
) -> list[str]:
    """Whitelist of Instagram URLs for interactive navigation."""
    handle = (username or "").strip().lstrip("@")
    mapping: dict[str, list[str]] = {
        "login": [_INSTAGRAM_LOGIN_URL],
        "home": [_INSTAGRAM_URL],
        "reels": [f"{_INSTAGRAM_BASE}/reels/"],
        "explore": [f"{_INSTAGRAM_BASE}/explore/"],
        "direct": [f"{_INSTAGRAM_BASE}/direct/inbox/"],
        "activity": [f"{_INSTAGRAM_BASE}/accounts/activity/"],
        "edit_profile": [f"{_INSTAGRAM_BASE}/accounts/edit/"],
        "profile": [f"{_INSTAGRAM_BASE}/{handle}/"] if handle else [_INSTAGRAM_URL],
    }
    if target == "auto":
        return [_INSTAGRAM_LOGIN_URL] if need_login else [_INSTAGRAM_URL]
    return mapping.get(target, [_INSTAGRAM_URL] if not need_login else [_INSTAGRAM_LOGIN_URL])

_GOTO_WARNING_MESSAGE = (
    "Instagram не открылся через прокси (HTTP-ошибка). "
    "Введите instagram.com вручную в браузере или смените прокси/режим на Десктоп."
)

_MANUAL_OPEN_HINT = (
    "Браузер запущен без автозахода на Instagram — нажмите «Открыть Instagram» "
    "или введите адрес вручную в окне VNC, чтобы снизить риск HTTP 429."
)

def _is_on_instagram(url: str | None) -> bool:
    return bool(url and "instagram.com" in url)


_YOUTUBE_STUDIO_URL = "https://studio.youtube.com"
_TIKTOK_STUDIO_URL = "https://www.tiktok.com/tiktokstudio/upload"
_GOOGLE_ACCOUNTS_URL = "https://accounts.google.com/"

# HEAD probes (same as ``curl -x PROXY -I`` from the API container).
STUDIO_HTTPS_PROBE_TARGETS: tuple[tuple[str, str], ...] = (
    ("studio.youtube.com", "https://studio.youtube.com/"),
    ("accounts.google.com", "https://accounts.google.com/"),
)


async def probe_studio_https_via_proxy(
    proxy_url: str,
    *,
    timeout_sec: float = 30.0,
) -> list[tuple[str, bool, str]]:
    """Return (host_label, ok, detail) for each Studio/Google probe URL."""
    out: list[tuple[str, bool, str]] = []
    for label, url in STUDIO_HTTPS_PROBE_TARGETS:
        ok, detail = await _probe_https_via_proxy(proxy_url, url, timeout_sec=timeout_sec)
        out.append((label, ok, detail))
    return out


def _studio_url_ladder(platform: str) -> list[str]:
    if platform == "youtube":
        return [_YOUTUBE_STUDIO_URL, _GOOGLE_ACCOUNTS_URL]
    if platform == "tiktok":
        return [_TIKTOK_STUDIO_URL]
    return []


def _is_suspicious_browser_url(url: str | None) -> bool:
    if not url or url == "about:blank":
        return True
    lower = url.lower()
    return lower.startswith("chrome-error://") or lower.startswith("chrome://newtab")


def _google_signin_rejected(url: str | None) -> bool:
    if not url:
        return False
    lower = url.lower()
    return "signin/rejected" in lower or "signin/v3/rejected" in lower


def _google_signin_rejected_warning() -> str:
    return (
        "Google отклонил вход («браузер небезопасен»). "
        "Смените прокси или: python -m app.cli proxy-studio-check <username>. "
        "Не используйте «Google автозаполнение» — введите логин вручную в VNC "
        "или кнопками «Вставить» после клика в поле. "
        "Если отказ повторяется: войдите в обычном Chrome и «Сохранить сессию и куки»."
    )


def _maybe_warn_google_signin_rejected(session: BrowserSessionState, url: str | None) -> None:
    if not _google_signin_rejected(url):
        return
    msg = _google_signin_rejected_warning()
    session.launch_warning = msg
    session.log("warn", "login", msg)


def _on_studio_platform(url: str | None, platform: str) -> bool:
    if not url:
        return False
    lower = url.lower()
    if platform == "youtube":
        return "studio.youtube.com" in lower or "accounts.google.com" in lower or "youtube.com" in lower
    if platform == "tiktok":
        return "tiktokstudio" in lower or "tiktok.com" in lower
    return False


def _studio_goto_warning(platform: str, http_status: int | None, page_url: str | None) -> str:
    label = "YouTube Studio" if platform == "youtube" else "TikTok Studio"
    if http_status is not None and http_status >= 400:
        return (
            f"{label} через прокси вернул HTTP {http_status}. "
            "Проверьте прокси (curl -x … https://studio.youtube.com), смените IP или войдите вручную в VNC."
        )
    if _is_suspicious_browser_url(page_url):
        return (
            f"{label} не открылся (страница пустая или зависла). "
            "Нажмите «Открыть Studio» / введите studio.youtube.com вручную; Google часто грузится медленно через mobile-прокси."
        )
    return (
        f"Не удалось открыть {label} автоматически. "
        "Используйте «Открыть Studio» или введите URL в окне браузера."
    )


async def _open_studio_urls(
    page,
    session: BrowserSessionState,
    *,
    platform: str,
    username: str,
    account,
    need_login: bool,
    autofill_login: bool,
) -> None:
    """Navigate Studio URL ladder; set launch_warning when landing fails."""
    urls = _studio_url_ladder(platform)
    if not urls:
        return

    last_http: int | None = None
    landed = False
    for idx, url in enumerate(urls):
        nav_status: dict[str, Any] = {}
        if idx == 0:
            session.log("info", "goto", f"Открываю {url}")
        else:
            session.log("info", "goto", f"Fallback: {url}")
        ok = await _try_goto_studio_url(page, url, username=username, nav_status=nav_status)
        last_http = nav_status.get("http_status")
        err_hint = nav_status.get("error")
        session.log(
            "info" if ok else "warn",
            "goto",
            (
                f"HTTP={last_http or '—'} url={page.url or '—'}"
                + (f" ({err_hint})" if err_hint and not ok else "")
                if ok or last_http or err_hint
                else f"Переход не удался: {page.url or '—'}"
            ),
        )
        if _on_studio_platform(page.url, platform):
            landed = True
            break
        if ok and not _is_suspicious_browser_url(page.url):
            landed = True
            break

    session.page_url = page.url
    if landed and not _is_suspicious_browser_url(page.url):
        if (
            platform == "youtube"
            and need_login
            and autofill_login
            and "accounts.google.com" in (page.url or "")
        ):
            await _try_google_studio_autofill(session, page, account)
        _maybe_warn_google_signin_rejected(session, page.url)
        return

    if _google_signin_rejected(page.url):
        _maybe_warn_google_signin_rejected(session, page.url)
        return

    session.launch_warning = _studio_goto_warning(platform, last_http, page.url)
    session.log("warn", "goto", session.launch_warning)


async def _try_google_studio_autofill(session: BrowserSessionState, page, account) -> None:
    from app.accounts.studio_login_service import resolve_studio_login_identifier
    from app.behavior.studio_playwright import _try_google_identifier, _try_google_password

    login_id = resolve_studio_login_identifier(account)
    password = (getattr(account, "password", None) or "").strip()
    if not login_id or not password:
        session.log("warn", "autofill", "Google autofill: нет email или пароля в карточке")
        return
    session.log("info", "autofill", f"Google: ввожу логин ({login_id})…")
    try:
        if await _try_google_identifier(page, login_id):
            if await _try_google_password(page, password):
                session.log("info", "autofill", "Google: форма отправлена")
            else:
                session.log("warn", "autofill", "Google: не удалось ввести пароль")
        else:
            session.log("warn", "autofill", "Google: поле логина не найдено")
    except Exception as exc:  # noqa: BLE001
        session.log("warn", "autofill", f"Google autofill: {exc}")
        logger.warning("browser_session.google_autofill_failed", username=session.username, error=str(exc))
    _maybe_warn_google_signin_rejected(session, page.url)


def _goto_warning_message(http_status: int | None) -> str:
    if http_status == 429:
        msg = (
            "Instagram ограничил запросы с этого IP прокси (HTTP 429). "
            "Подождите 30–60 минут, не перезапускайте браузер часто, или смените прокси. "
            "После паузы попробуйте режим «Десктоп»."
        )
        return msg
    if http_status is not None:
        return (
            f"Страница логина вернула HTTP {http_status} через прокси. {_GOTO_WARNING_MESSAGE}"
        )
    return _GOTO_WARNING_MESSAGE


_RATE_LIMIT_STATUSES = frozenset({429, 503})


def _is_rate_limited(
    http_status: int | None,
    url: str | None,
    *,
    error_text: str | None = None,
) -> bool:
    if http_status in _RATE_LIMIT_STATUSES:
        return True
    if error_text and "429" in error_text:
        return True
    if http_status == 429:
        return True
    return bool(
        url
        and url.startswith("chrome-error://")
        and http_status in _RATE_LIMIT_STATUSES
    )


def _proxy_login_blocked(
    *,
    login_reachable: bool | None,
    login_http_status: int | None,
) -> bool:
    """True only when we have evidence the login page is blocked.

    Empty MINIMAL cache sets ``login_reachable=False`` with ``http_status=None``
    (unknown). That must not skip auto-open — otherwise Instagram never opens
    on a fresh proxy.
    """
    if login_http_status in _RATE_LIMIT_STATUSES:
        return True
    if login_http_status in (403, 451):
        return True
    if login_reachable is False and login_http_status is not None:
        return True
    return False


def _warning_from_proxy_preflight(
    *,
    login_reachable: bool | None,
    login_http_status: int | None,
) -> str:
    if login_http_status == 429:
        return _goto_warning_message(429)
    if login_reachable is False:
        if login_http_status:
            return (
                f"Страница логина Instagram недоступна через этот прокси (HTTP {login_http_status}). "
                "Смените IP прокси или подождите — эмуляция браузера это не обходит."
            )
        return (
            "Страница логина Instagram недоступна через этот прокси. "
            "Смените IP прокси или подождите — эмуляция браузера это не обходит."
        )
    return _goto_warning_message(login_http_status)


async def _probe_https_via_proxy(proxy_url: str, target_url: str, *, timeout_sec: float = 25.0) -> tuple[bool, str]:
    """HEAD through proxy — same path as ``curl -x`` from the API container."""

    def _run() -> tuple[bool, str]:
        try:
            with httpx.Client(
                proxy=proxy_url,
                timeout=timeout_sec,
                follow_redirects=True,
            ) as client:
                response = client.head(target_url)
                return True, f"HTTP {response.status_code}"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc).replace("\n", " ")[:220]

    return await asyncio.to_thread(_run)


_STUDIO_NAV_TIMEOUT_MS = 120_000
_STUDIO_POST_COMMIT_MS = 45_000


async def _try_goto_studio_url(
    page,
    url: str,
    *,
    username: str,
    nav_status: dict[str, Any],
) -> bool:
    """Studio/Google navigation — domcontentloaded first, then commit fallback (slow mobile proxy)."""
    configured = settings.browser_goto_timeout_sec * 1000
    timeout_ms = max(configured, _STUDIO_NAV_TIMEOUT_MS)

    def on_response(response) -> None:
        try:
            request = response.request
            if request.is_navigation_request() and request.frame == page.main_frame:
                nav_status["http_status"] = response.status
                nav_status["url"] = response.url
        except Exception:
            pass

    page.on("response", on_response)
    last_exc: Exception | None = None
    try:
        for wait_until in ("domcontentloaded", "commit"):
            nav_status["wait_until"] = wait_until
            try:
                await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
                if wait_until == "commit":
                    try:
                        await page.wait_for_load_state(
                            "domcontentloaded", timeout=_STUDIO_POST_COMMIT_MS
                        )
                    except Exception as post_exc:
                        nav_status["post_commit"] = str(post_exc)[:200]
                logger.info(
                    "browser_session.studio_goto_ok",
                    username=username,
                    url=url,
                    wait_until=wait_until,
                    page_url=page.url,
                    http_status=nav_status.get("http_status"),
                )
                if page.url and not _is_suspicious_browser_url(page.url):
                    return True
                if _is_rate_limited(nav_status.get("http_status"), page.url):
                    return False
                if wait_until == "commit":
                    return True
            except Exception as exc:
                last_exc = exc
                nav_status["error"] = str(exc)[:300]
                logger.warning(
                    "browser_session.studio_goto_attempt_failed",
                    username=username,
                    url=url,
                    wait_until=wait_until,
                    page_url=page.url,
                    error=str(exc),
                )
                if page.url and not _is_suspicious_browser_url(page.url):
                    return True
                if _is_suspicious_browser_url(page.url) and wait_until == "domcontentloaded":
                    continue
                break
        if last_exc is not None:
            nav_status["error"] = str(last_exc)[:300]
        return bool(page.url and not _is_suspicious_browser_url(page.url))
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass


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
            if _is_rate_limited(nav_status.get("http_status"), page.url):
                return False
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
            if _is_rate_limited(
                nav_status.get("http_status"),
                page.url,
                error_text=str(exc),
            ):
                return False
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


async def _open_instagram_browser(
    page,
    *,
    username: str,
    need_login: bool,
    target: NavTarget = "auto",
) -> tuple[str | None, int | None]:
    """Open Instagram via a URL ladder; never fall back to about:blank."""
    urls = _nav_urls_for_target(target, username=username, need_login=need_login)

    nav_status: dict[str, Any] = {}
    last_http_status: int | None = None
    on_ig = False

    for url in urls:
        nav_status.clear()
        landed = await _try_goto_url(page, url, username=username, nav_status=nav_status)
        last_http_status = nav_status.get("http_status")
        if _is_rate_limited(last_http_status, page.url):
            break
        if landed or _is_on_instagram(page.url):
            on_ig = True
            # Explicit page targets: land and return. Login/auto may wait for form.
            if target not in ("auto", "login"):
                return None, last_http_status
            if not need_login or url == _INSTAGRAM_LOGIN_URL:
                return None, last_http_status
            if await _login_form_visible(page):
                return None, last_http_status

    if on_ig:
        return None, last_http_status
    if _is_rate_limited(last_http_status, page.url):
        return _goto_warning_message(429), last_http_status or 429
    return _goto_warning_message(last_http_status), last_http_status


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
    proxy_instagram_login_http_status: int | None = None
    display: int = 0
    ws_port: int = 0
    vnc_path: str = ""
    page_url: str | None = None
    login_surface: LoginSurface = "mobile"
    started_at: float = field(default_factory=time.monotonic)
    action_logs: list[dict[str, str]] = field(default_factory=list)
    last_logged_url: str | None = None
    vnc_stack: VncStack | None = None
    pw: Any = None
    browser: Any = None
    context: Any = None
    page: Any = None
    poll_task: asyncio.Task | None = None
    auto_stop_task: asyncio.Task | None = None
    studio_nav_task: asyncio.Task | None = None
    login_orchestration: bool = False

    def log(self, level: LogLevel, step: str, message: str) -> None:
        line = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "step": step,
            "message": message,
        }
        self.action_logs.append(line)
        if len(self.action_logs) > _MAX_ACTION_LOGS:
            del self.action_logs[: len(self.action_logs) - _MAX_ACTION_LOGS]
        log_fn = logger.info if level == "info" else logger.warning if level == "warn" else logger.error
        log_fn("browser_session.action", username=self.username, step=step, level=level, message=message)


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

    def set_login_orchestration(self, username: str, active: bool = True) -> None:
        session = self._sessions.get(username)
        if session is not None:
            session.login_orchestration = active

    def login_orchestration_active(self, username: str) -> bool:
        session = self._sessions.get(username)
        if session is None:
            return False
        if session.status in (BrowserSessionStatus.stopped, BrowserSessionStatus.error):
            return False
        return bool(session.login_orchestration)

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
        session.proxy_instagram_login_http_status = getattr(
            snapshot, "instagram_login_http_status", None
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
                "proxy_instagram_login_http_status": None,
                "logs": [],
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
            "proxy_instagram_login_http_status": session.proxy_instagram_login_http_status,
            "login_orchestration": session.login_orchestration,
            "logs": list(session.action_logs),
        }

    def persist_action_logs(
        self,
        db: Session,
        account,
        *,
        status: Literal["ok", "warn", "fail"] = "ok",
        summary: str,
    ) -> int | None:
        session = self._sessions.get(account.username)
        if session is None or not session.action_logs:
            return None
        collector = DiagnosticCollector(
            db,
            kind=DiagnosticRunKind.browser_session,
            account_id=account.id,
        )
        for item in session.action_logs:
            level = item.get("level", "info")
            if level not in ("info", "warn", "error"):
                level = "info"
            collector.log(level, str(item.get("step") or "browser"), str(item.get("message") or ""))
        collector.finish(status, summary)
        return collector.run_id

    async def start_session(
        self,
        account,
        proxy,
        *,
        autofill_login: bool = False,
        surface: LoginSurface | str | None = None,
        proxy_snapshot: Any = None,
        studio_autofill: bool = False,
    ) -> BrowserSessionState:
        username = account.username
        platform_value = _account_platform_value(account)
        if platform_value in ("youtube", "tiktok"):
            resolved_surface = "desktop"
        else:
            resolved_surface = resolve_playwright_surface(
                surface or getattr(account, "login_surface", None)
            )
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
                raise RuntimeError(
                    "интерактивный браузер отключён (задайте BROWSER_VNC_ENABLED=true)"
                )
            if not vnc_stack_available():
                raise RuntimeError("Xvfb/x11vnc/websockify не установлены на сервере")
            if not playwright_browsers_available():
                raise RuntimeError(
                    "Chromium не установлен — выполните install-playwright на сервере"
                )

            active = [
                s
                for s in self._sessions.values()
                if s.username != username
                and s.status
                not in (
                    BrowserSessionStatus.stopped,
                    BrowserSessionStatus.error,
                    BrowserSessionStatus.saved,
                )
            ]
            if len(active) >= settings.browser_max_sessions:
                names = ", ".join(s.username for s in active[:3])
                raise RuntimeError(
                    f"Уже открыт браузер ({names}). Закройте его — лимит "
                    f"{settings.browser_max_sessions} сессия(й) для экономии RAM."
                )

            display = self._next_display()
            rfb_port, ws_port = allocate_ports(display)
            lightweight = settings.browser_lightweight
            desktop_geometry = _studio_desktop_geometry(platform_value)
            vnc = VncStack(
                display=display,
                rfb_port=rfb_port,
                ws_port=ws_port,
                screen=vnc_screen_size(
                    resolved_surface,
                    lightweight=lightweight,
                    desktop_geometry=desktop_geometry,
                ),
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
                proxy_instagram_login_http_status=getattr(
                    proxy_snapshot, "instagram_login_http_status", None
                ),
            )
            session.log(
                "info",
                "start",
                f"Запуск браузера (surface={resolved_surface}, display=:{display}, lightweight={lightweight})",
            )
            self._sessions[username] = session

        try:
            async def _fetch_snapshot():
                if proxy_snapshot is not None:
                    return proxy_snapshot
                try:
                    return await asyncio.to_thread(
                        health_check_cached,
                        proxy.url,
                        force=False,
                        scope=HealthCheckScope.MINIMAL,
                    )
                except ProxyError as exc:
                    session.log("warn", "proxy", f"Предпроверка прокси не удалась: {exc}")
                    return None
                except Exception as exc:  # noqa: BLE001
                    session.log("warn", "proxy", f"Предпроверка прокси: {exc}")
                    return None

            session.log("info", "vnc", "Старт VNC + предпроверка прокси…")
            snap, _ = await asyncio.gather(_fetch_snapshot(), vnc.start())
            if snap is not None:
                self.apply_proxy_snapshot(username, snap)
                session.log(
                    "info",
                    "proxy",
                    (
                        f"Прокси ок ip={session.proxy_ip or '—'}; "
                        f"вход доступен={session.proxy_instagram_login_reachable}; "
                        f"http входа={session.proxy_instagram_login_http_status}"
                    ),
                )
            session.log("info", "vnc", f"VNC готов (ws_port={ws_port})")
            if platform_value in ("youtube", "tiktok"):
                probe_rows = await probe_studio_https_via_proxy(proxy.url, timeout_sec=30.0)
                all_ok = True
                for host, ok_row, detail in probe_rows:
                    level_row: LogLevel = "info" if ok_row else "warn"
                    session.log(
                        level_row,
                        "proxy",
                        f"HTTPS {host} через прокси: {detail}",
                    )
                    if not ok_row:
                        all_ok = False
                if not all_ok:
                    parts = "; ".join(f"{h}={d}" for h, _ok, d in probe_rows if not _ok)
                    session.launch_warning = (
                        f"Прокси не открывает Google/Studio ({parts}). "
                        f"Смените mobile-IP или: python -m app.cli proxy-studio-check {username}"
                    )
            await self._launch_browser(
                session,
                account,
                proxy,
                autofill_login=autofill_login,
                surface=resolved_surface,
                studio_autofill=studio_autofill,
            )
            session.status = BrowserSessionStatus.running
            session.log(
                "info",
                "browser",
                f"Chromium запущен; URL={session.page_url or '—'}",
            )
            session.poll_task = asyncio.create_task(self._poll_session(session, account))
            timeout_sec = settings.browser_session_timeout_min * 60
            session.auto_stop_task = asyncio.create_task(self._auto_stop(username, timeout_sec))
            return session
        except Exception as exc:
            session.status = BrowserSessionStatus.error
            session.error = str(exc)
            session.log("error", "start", f"Ошибка запуска: {exc}")
            logger.error("browser_session.start_failed", username=username, error=str(exc))
            await self._cleanup_session(session, remove=False)
            raise

    async def _launch_browser(
        self,
        session: BrowserSessionState,
        account,
        proxy,
        *,
        autofill_login: bool,
        surface: LoginSurface,
        studio_autofill: bool = False,
    ) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("playwright не установлен") from exc

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

        platform_value = _account_platform_value(account)
        studio_profile = None
        instagram_web_profile = None
        ig_chrome_major: str | None = None
        if platform_value in ("youtube", "tiktok"):
            fingerprint = None
            studio_profile = ensure_studio_desktop_profile(
                account.username, platform_value, proxy_country=proxy.country
            )
            locale = studio_profile.locale
        else:
            fingerprint = load_fingerprint(account.username)
            if surface == "desktop":
                instagram_web_profile = ensure_desktop_playwright_profile(
                    account.username, "instagram", proxy_country=proxy.country
                )
                locale = instagram_web_profile.locale
            else:
                ig_chrome_major = ensure_playwright_chrome_major(account.username)
                locale = getattr(fingerprint, "locale", None) or "en-US"
        tz_id = normalize_playwright_timezone(proxy.timezone, country=proxy.country)

        proxy_arg = _parse_proxy(proxy.url)
        if not proxy_arg:
            raise RuntimeError("для интерактивного браузера нужен прокси")

        state_file = playwright_state_path(account.username, platform_value)
        if platform_value == "instagram":
            has_saved_session = state_file.exists() and storage_state_has_session(account.username)
        else:
            has_saved_session = state_file.exists()
        display_env = os.environ.copy()
        display_env["DISPLAY"] = vnc_stack_display(session)
        lightweight = settings.browser_lightweight
        desktop_geometry = _studio_desktop_geometry(platform_value)

        session.pw = await async_playwright().start()
        if platform_value in ("youtube", "tiktok"):
            chromium_args = studio_vnc_launch_args(desktop_geometry)
            ctx_lightweight = False
        else:
            chromium_args = browser_launch_args(
                surface,
                lightweight=lightweight,
                desktop_geometry=desktop_geometry,
            )
            ctx_lightweight = lightweight

        launch_kwargs: dict[str, Any] = {
            "headless": False,
            "ignore_default_args": ["--enable-automation"],
            "args": chromium_args,
            "proxy": proxy_arg,
            "env": display_env,
        }
        if platform_value in ("youtube", "tiktok"):
            vnc_channel = normalize_playwright_channel(settings.browser_vnc_channel)
            launch_kwargs.update(chromium_launch_channel_kwargs(vnc_channel))
        session.browser = await session.pw.chromium.launch(**launch_kwargs)

        if studio_profile is not None:
            context_kwargs = studio_playwright_context_kwargs(
                studio_profile,
                timezone_id=tz_id,
                storage_state_path=str(state_file) if has_saved_session else None,
            )
        elif instagram_web_profile is not None:
            context_kwargs = desktop_playwright_context_kwargs(
                instagram_web_profile,
                timezone_id=tz_id,
                storage_state_path=str(state_file) if has_saved_session else None,
            )
        else:
            context_kwargs = playwright_context_kwargs(
                surface,
                fingerprint=fingerprint,
                locale=locale,
                timezone_id=tz_id,
                storage_state_path=str(state_file) if has_saved_session else None,
                lightweight=ctx_lightweight,
                desktop_geometry=desktop_geometry,
                chrome_major=ig_chrome_major,
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
        need_login = not has_saved_session
        session.log(
            "info",
            "browser",
            f"Контекст готов; storage_state={'да' if has_saved_session else 'нет'}; need_login={need_login}",
        )
        platform_value = _account_platform_value(account)
        do_autofill = studio_autofill or (
            autofill_login and settings.browser_autofill_on_start
        )
        if platform_value in ("youtube", "tiktok"):
            session.page_url = page.url
            session.last_logged_url = page.url

            async def _run_studio_nav() -> None:
                try:
                    await _open_studio_urls(
                        page,
                        session,
                        platform=platform_value,
                        username=session.username,
                        account=account,
                        need_login=need_login,
                        autofill_login=do_autofill,
                    )
                    session.page_url = page.url
                    session.last_logged_url = page.url
                    await self._refresh_code_state(session)
                except Exception as exc:  # noqa: BLE001
                    session.log("error", "goto", f"Studio navigation: {exc}")
                    logger.warning(
                        "browser_session.studio_nav_failed",
                        username=session.username,
                        error=str(exc),
                    )

            session.studio_nav_task = asyncio.create_task(_run_studio_nav())
            return

        await self._maybe_open_home(
            session,
            account,
            proxy,
            page=page,
            need_login=need_login,
            autofill_login=autofill_login,
        )

        session.page_url = page.url
        session.last_logged_url = page.url
        await self._refresh_code_state(session)

    async def _maybe_open_home(
        self,
        session: BrowserSessionState,
        account,
        proxy,
        *,
        page,
        need_login: bool,
        autofill_login: bool,
    ) -> None:
        value = _account_platform_value(account)
        if value in ("youtube", "tiktok"):
            await _open_studio_urls(
                page,
                session,
                platform=value,
                username=session.username,
                account=account,
                need_login=need_login,
                autofill_login=autofill_login,
            )
            session.page_url = page.url
            await self._refresh_code_state(session)
            return
        await self._maybe_open_instagram(
            session,
            account,
            proxy,
            page=page,
            need_login=need_login,
            autofill_login=autofill_login,
        )

    async def _maybe_open_instagram(
        self,
        session: BrowserSessionState,
        account,
        proxy,
        *,
        page,
        need_login: bool,
        autofill_login: bool,
    ) -> None:
        blocked = need_login and _proxy_login_blocked(
            login_reachable=session.proxy_instagram_login_reachable,
            login_http_status=session.proxy_instagram_login_http_status,
        )
        if blocked:
            session.launch_warning = _warning_from_proxy_preflight(
                login_reachable=session.proxy_instagram_login_reachable,
                login_http_status=session.proxy_instagram_login_http_status,
            )
            session.log(
                "error",
                "goto",
                (
                    f"Автопереход пропущен: вход заблокирован "
                    f"(доступен={session.proxy_instagram_login_reachable}, "
                    f"http={session.proxy_instagram_login_http_status}). {session.launch_warning}"
                ),
            )
            return

        if not settings.browser_auto_open_instagram:
            session.launch_warning = _MANUAL_OPEN_HINT
            session.log("warn", "goto", _MANUAL_OPEN_HINT)
            return

        session.log(
            "info",
            "goto",
            f"Автопереход на Instagram ({'login' if need_login else 'home'})…",
        )
        await self._navigate_instagram_and_maybe_autofill(
            session,
            account,
            proxy,
            page=page,
            need_login=need_login,
            autofill_login=autofill_login and settings.browser_autofill_on_start,
            target="auto",
        )

    async def _navigate_instagram_and_maybe_autofill(
        self,
        session: BrowserSessionState,
        account,
        proxy,
        *,
        page,
        need_login: bool,
        autofill_login: bool,
        target: NavTarget = "auto",
    ) -> None:
        warning, login_http_status = await _open_instagram_browser(
            page,
            username=account.username,
            need_login=need_login,
            target=target,
        )
        if warning:
            session.launch_warning = warning
            session.log("warn", "goto", warning)
        if login_http_status is not None:
            session.proxy_instagram_login_http_status = login_http_status
            if login_http_status >= 400:
                session.proxy_instagram_login_reachable = False
                note_proxy_login_http_status(proxy.url, int(login_http_status))
            session.log(
                "info",
                "goto",
                f"HTTP status навигации: {login_http_status}; URL={page.url}",
            )

        await _human_wait(0.05, 0.15)
        on_ig = _is_on_instagram(page.url)
        if on_ig or not session.launch_warning:
            await _accept_cookie_banner(page)
            if on_ig:
                session.log("info", "goto", f"На Instagram: {page.url}")
        elif not on_ig:
            session.log(
                "warn",
                "goto",
                f"Instagram не загрузился, текущий URL={page.url or '—'}",
            )
        session.page_url = page.url
        session.last_logged_url = page.url

        if (
            autofill_login
            and target in ("auto", "login")
            and not await _is_logged_in(session.context, page)
            and (on_ig or not session.launch_warning)
        ):
            login_id = resolve_login_identifier(account)
            session.log("info", "autofill", f"Автозаполнение логина ({login_id})…")
            try:
                await _ensure_login_page(page, fast=True)
                await _fill_login_field(page, password=False, text=login_id)
                await _human_wait(0.1, 0.25)
                await _fill_login_field(page, password=True, text=account.password)
                await _submit_login_form(page)
                await _human_wait(0.3, 0.6)
                await _try_submit_totp(page, account.totp_seed)
                await _dismiss_post_login_modals(page)
                session.log("info", "autofill", "Форма логина отправлена")
            except Exception as exc:
                session.log("warn", "autofill", f"Автозаполнение не удалось: {exc}")
                logger.warning("browser_session.autofill_failed", username=account.username, error=str(exc))

        session.page_url = page.url

    async def open_instagram(
        self,
        account,
        proxy,
        *,
        autofill_login: bool = False,
        target: NavTarget = "auto",
    ) -> None:
        session = self._sessions.get(account.username)
        if session is None or session.page is None or session.context is None:
            raise RuntimeError("нет активной браузерной сессии для этого аккаунта")
        if session.status not in (
            BrowserSessionStatus.running,
            BrowserSessionStatus.awaiting_code,
            BrowserSessionStatus.saved,
        ):
            raise RuntimeError("браузерная сессия не запущена")

        state_file = playwright_state_path(account.username, _account_platform_value(account))
        session.launch_warning = None
        platform_value = _account_platform_value(account)
        if platform_value == "instagram":
            need_login = not (
                state_file.exists() and storage_state_has_session(account.username)
            )
        else:
            need_login = not state_file.exists()
        session.log(
            "info",
            "goto",
            f"Ручной переход target={target}, autofill={autofill_login}, need_login={need_login}",
        )
        if platform_value in ("youtube", "tiktok"):
            await _open_studio_urls(
                session.page,
                session,
                platform=platform_value,
                username=session.username,
                account=account,
                need_login=need_login,
                autofill_login=autofill_login,
            )
            session.page_url = session.page.url
            await self._refresh_code_state(session)
            return
        await self._navigate_instagram_and_maybe_autofill(
            session,
            account,
            proxy,
            page=session.page,
            need_login=need_login,
            autofill_login=autofill_login,
            target=target,
        )
        await self._refresh_code_state(session)

    async def _poll_session(self, session: BrowserSessionState, account) -> None:
        while session.status in (BrowserSessionStatus.running, BrowserSessionStatus.awaiting_code):
            try:
                if session.page is None or session.context is None:
                    break
                platform_value = _account_platform_value(account)
                if await _platform_logged_in(session.context, session.page, platform_value):
                    session.awaiting_code = False
                    if session.status == BrowserSessionStatus.awaiting_code:
                        session.status = BrowserSessionStatus.running
                else:
                    await self._refresh_code_state(session)
                session.page_url = session.page.url
                if session.page_url != session.last_logged_url:
                    prev = session.last_logged_url or "—"
                    session.last_logged_url = session.page_url
                    session.log(
                        "info",
                        "poll",
                        f"URL: {prev} → {session.page_url}",
                    )
                    if session.page_url and (
                        session.page_url.startswith("chrome-error://")
                        or session.page_url == "about:blank"
                    ):
                        session.log(
                            "warn",
                            "poll",
                            f"Подозрительный URL страницы: {session.page_url}",
                        )
                    _maybe_warn_google_signin_rejected(session, session.page_url)
            except Exception as exc:
                session.log("warn", "poll", f"Ошибка опроса: {exc}")
                logger.warning("browser_session.poll_error", username=session.username, error=str(exc))
            await asyncio.sleep(2.0)

    async def _refresh_code_state(self, session: BrowserSessionState) -> None:
        if session.page is None:
            return
        needs_code = await _detect_2fa_required(session.page) or await _detect_challenge(session.page)
        was_awaiting = session.awaiting_code
        session.awaiting_code = needs_code
        if needs_code and session.status == BrowserSessionStatus.running:
            session.status = BrowserSessionStatus.awaiting_code
        if needs_code and not was_awaiting:
            session.log("warn", "code", "Обнаружен 2FA/challenge — нужен код подтверждения")

    _PASTE_TEXT_MAX_LEN = 2000

    @staticmethod
    def _sanitize_paste_text(text: str) -> str:
        cleaned = "".join(
            ch for ch in text if ch in ("\n", "\t") or (ord(ch) >= 32 and ord(ch) != 127)
        )
        return cleaned[: BrowserSessionManager._PASTE_TEXT_MAX_LEN]

    async def paste_text(self, account, text: str) -> None:
        session = self._sessions.get(account.username)
        if session is None or session.page is None:
            raise RuntimeError("нет активной браузерной сессии для этого аккаунта")
        if session.status not in (
            BrowserSessionStatus.running,
            BrowserSessionStatus.awaiting_code,
        ):
            raise RuntimeError("браузерная сессия не запущена")
        payload = self._sanitize_paste_text(text or "")
        if not payload:
            raise ValueError("пустой текст для вставки")
        await session.page.keyboard.insert_text(payload)
        session.log("info", "paste", f"Вставлено в VNC: {len(payload)} символов")

    async def submit_code(self, db: Session, account, code: str | None) -> bool:
        session = self._sessions.get(account.username)
        if session is None or session.page is None:
            raise RuntimeError("нет активной браузерной сессии для этого аккаунта")

        resolved = (code or "").strip()
        if not resolved:
            resolved = consume_next_backup_code(db, account) or ""
        if not resolved:
            raise ValueError("нужен код подтверждения")

        session.log("info", "code", "Отправка кода подтверждения…")
        ok = await submit_verification_code(session.page, resolved)
        if not ok:
            session.log("error", "code", "Поле для кода на странице не найдено")
            raise RuntimeError("на странице не найдено поле для кода подтверждения")

        await _human_wait(0.5, 1.0)
        await _dismiss_post_login_modals(session.page)
        await self._refresh_code_state(session)
        session.page_url = session.page.url
        if await _is_logged_in(session.context, session.page):
            session.status = BrowserSessionStatus.running
            session.awaiting_code = False
            session.log("info", "code", "Вход подтверждён после кода")
        else:
            session.log("warn", "code", f"Код отправлен; URL={session.page_url}")
        return ok

    async def save_session(self, db: Session, account) -> dict[str, Any]:
        session = self._sessions.get(account.username)
        if session is None or session.context is None:
            raise RuntimeError("нет активной браузерной сессии для этого аккаунта")

        if session.page is None or not await _platform_logged_in(
            session.context, session.page, _account_platform_value(account)
        ):
            platform = _account_platform_value(account)
            label = {"youtube": "YouTube", "tiktok": "TikTok"}.get(platform, "Instagram")
            session.log("error", "save", f"Нет cookies {label} — сначала войдите в браузере")
            raise RuntimeError(
                f"Сначала войдите в {label} в браузере — cookies площадки не найдены"
            )

        platform = _account_platform_value(account)
        state_file = playwright_state_write_path(account.username, platform)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        await session.context.storage_state(path=str(state_file))
        data = json.loads(state_file.read_text(encoding="utf-8"))
        if platform != "instagram":
            session.status = BrowserSessionStatus.saved
            session.awaiting_code = False
            session.log("info", "save", f"Playwright cookies {platform} сохранены в state.json")
            return {
                "session_imported": False,
                "session_id_saved": False,
                "playwright_state_saved": True,
            }

        session_id = sessionid_from_playwright_state_data(data)
        imported = import_playwright_session_to_account(db, account, session_id=session_id)
        if not imported:
            session.log("error", "save", "Не удалось извлечь sessionid из browser state")
            raise RuntimeError("не удалось извлечь sessionid из состояния браузера")

        session.status = BrowserSessionStatus.saved
        session.awaiting_code = False
        session.log(
            "info",
            "save",
            (
                f"Web sessionid сохранён в БД ({sessionid_diag_label(session_id)}). "
                "Для автопостинга нужен mint mobile или вход по паролю в очереди."
            ),
        )
        return {
            "session_imported": True,
            "session_id_saved": bool(session_id),
        }

    async def stop_session(self, username: str) -> None:
        async with self._lock:
            session = self._sessions.get(username)
            if session is None:
                return
            session.log("info", "stop", "Остановка браузера")
            await self._cleanup_session(session, remove=False)
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
        for task in (session.poll_task, session.auto_stop_task, session.studio_nav_task):
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
        session.ws_port = 0
        session.vnc_path = ""
        session.poll_task = None
        session.auto_stop_task = None

        session.login_orchestration = False
        if remove:
            self._sessions.pop(session.username, None)


def vnc_stack_display(session: BrowserSessionState) -> str:
    return f":{session.display}"


browser_session_manager = BrowserSessionManager()
