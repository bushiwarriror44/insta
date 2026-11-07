"""Headless Instagram web session liveness (Playwright state on disk)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.accounts.device_factory import load_fingerprint
from app.accounts.playwright_session import playwright_state_path, storage_state_has_session
from app.accounts.studio_desktop_profile import ensure_desktop_playwright_profile
from app.accounts.studio_desktop_profile import desktop_playwright_context_kwargs
from app.accounts.device_factory import ensure_playwright_chrome_major
from app.behavior.playwright_channel import (
    chromium_launch_channel_kwargs,
    normalize_playwright_channel,
)
from app.behavior.playwright_surface import resolve_playwright_surface, playwright_context_kwargs
from app.behavior.warmup_playwright import (
    _has_auth_cookies,
    _parse_proxy,
    playwright_browsers_available,
)
from app.config import settings

_NAV_TIMEOUT_MS = 60_000
_INSTAGRAM_HOME = "https://www.instagram.com/"


@dataclass
class InstagramWebLivenessResult:
    ok: bool
    challenge: bool = False
    error: str | None = None
    page_url: str | None = None


def _instagram_launch_kwargs(*, headless: bool, proxy_arg: dict | None) -> dict:
    launch_kw: dict = {"headless": headless, "proxy": proxy_arg}
    channel = normalize_playwright_channel(settings.playwright_instagram_channel)
    launch_kw.update(chromium_launch_channel_kwargs(channel))
    return launch_kw


async def _async_probe_instagram_web_liveness(
    *,
    username: str,
    proxy_url: str,
    login_surface: str | None,
    timezone_id: str,
    proxy_country: str | None,
    headless: bool = True,
) -> InstagramWebLivenessResult:
    if not storage_state_has_session(username):
        return InstagramWebLivenessResult(
            ok=False,
            error="Нет Playwright state с sessionid — web liveness пропущен",
        )
    if not (proxy_url or "").strip():
        return InstagramWebLivenessResult(ok=False, error="нужен прокси")
    if not playwright_browsers_available():
        return InstagramWebLivenessResult(ok=False, error="Chromium не установлен")

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        return InstagramWebLivenessResult(ok=False, error=f"playwright не установлен: {exc}")

    surface = resolve_playwright_surface(login_surface)
    state_file = playwright_state_path(username, "instagram")
    proxy_arg = _parse_proxy(proxy_url)
    fingerprint = load_fingerprint(username)

    desktop_profile = None
    chrome_major = None
    locale = "en-US"
    if surface == "desktop":
        desktop_profile = ensure_desktop_playwright_profile(
            username, "instagram", proxy_country=proxy_country
        )
        locale = desktop_profile.locale
    else:
        chrome_major = ensure_playwright_chrome_major(username)
        if fingerprint is not None:
            locale = getattr(fingerprint, "locale", None) or locale

    async with async_playwright() as p:
        browser = await p.chromium.launch(**_instagram_launch_kwargs(headless=headless, proxy_arg=proxy_arg))
        try:
            if desktop_profile is not None:
                ctx_kw = desktop_playwright_context_kwargs(
                    desktop_profile,
                    timezone_id=timezone_id,
                    storage_state_path=str(state_file),
                )
            else:
                ctx_kw = playwright_context_kwargs(
                    surface,
                    fingerprint=fingerprint,
                    locale=locale,
                    timezone_id=timezone_id,
                    storage_state_path=str(state_file),
                    chrome_major=chrome_major,
                )
            context = await browser.new_context(**ctx_kw)
            page = await context.new_page()
            await page.goto(_INSTAGRAM_HOME, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
            await asyncio.sleep(2.0)
            cookies = await context.cookies()
            url = page.url or ""
            on_login = "/accounts/login" in url
            has_session = _has_auth_cookies(cookies)
            if has_session and not on_login:
                return InstagramWebLivenessResult(ok=True, page_url=url)
            if on_login or not has_session:
                return InstagramWebLivenessResult(
                    ok=False,
                    error="Instagram перенаправил на вход — web-cookies устарели",
                    page_url=url,
                )
            return InstagramWebLivenessResult(ok=False, error="Не удалось подтвердить web-сессию", page_url=url)
        finally:
            await browser.close()


def probe_instagram_web_liveness(
    *,
    username: str,
    proxy_url: str,
    login_surface: str | None = None,
    timezone_id: str = "UTC",
    proxy_country: str | None = None,
    headless: bool | None = None,
) -> InstagramWebLivenessResult:
    headless = settings.playwright_headless if headless is None else headless
    try:
        return asyncio.run(
            _async_probe_instagram_web_liveness(
                username=username,
                proxy_url=proxy_url,
                login_surface=login_surface,
                timezone_id=timezone_id,
                proxy_country=proxy_country,
                headless=headless,
            )
        )
    except Exception as exc:  # noqa: BLE001
        return InstagramWebLivenessResult(ok=False, error=str(exc))
