"""Headless Playwright login for YouTube Studio and TikTok Studio."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Optional

from app.accounts.cookie_formats import studio_session_ready
from app.accounts.playwright_session import playwright_state_path, save_playwright_state
from app.accounts.studio_desktop_profile import (
    ensure_studio_desktop_profile,
    studio_playwright_context_kwargs,
)
from app.behavior.playwright_channel import chromium_launch_channel_kwargs, normalize_playwright_channel
from app.behavior.warmup_playwright import _parse_proxy, playwright_browsers_available
from app.config import settings
from app.logging_setup import get_logger

StatusCallback = Callable[[str, Optional[str]], None]

logger = get_logger(__name__)

StudioPlatform = Literal["youtube", "tiktok"]

YOUTUBE_STUDIO_URL = "https://studio.youtube.com"
TIKTOK_STUDIO_URL = "https://www.tiktok.com/tiktokstudio/upload"

_NAV_TIMEOUT_MS = 90_000
_STEP_WAIT_MS = 15_000


def _studio_chromium_launch_kwargs(*, headless: bool, proxy) -> dict:
    launch_kw: dict = {"headless": headless, "proxy": proxy}
    channel = normalize_playwright_channel(settings.playwright_studio_channel)
    launch_kw.update(chromium_launch_channel_kwargs(channel))
    return launch_kw


@dataclass
class StudioLoginResult:
    ok: bool
    challenge: bool = False
    error: str | None = None
    page_url: str | None = None


@dataclass
class StudioLivenessResult:
    ok: bool
    challenge: bool = False
    error: str | None = None
    page_url: str | None = None


def evaluate_studio_liveness(
    *,
    page_url: str,
    platform: StudioPlatform,
    needs_login: bool,
    challenge: bool,
) -> StudioLivenessResult:
    """Pure check after navigating to Studio with stored cookies."""
    url = page_url or ""
    if challenge:
        return StudioLivenessResult(
            ok=False,
            challenge=True,
            error="Studio или Google запросили подтверждение (2FA / CAPTCHA)",
            page_url=url,
        )
    if needs_login:
        return StudioLivenessResult(
            ok=False,
            error="Cookies на диске есть, но Studio перенаправил на вход",
            page_url=url,
        )
    if platform == "youtube":
        if "studio.youtube.com" not in url.lower():
            return StudioLivenessResult(
                ok=False,
                error="Не удалось открыть YouTube Studio с текущими cookies",
                page_url=url,
            )
    else:
        lower = url.lower()
        if "tiktokstudio" not in lower and "tiktok.com" not in lower:
            return StudioLivenessResult(
                ok=False,
                error="Не удалось открыть TikTok Studio с текущими cookies",
                page_url=url,
            )
    return StudioLivenessResult(ok=True, page_url=url)


def _studio_url(platform: StudioPlatform) -> str:
    return YOUTUBE_STUDIO_URL if platform == "youtube" else TIKTOK_STUDIO_URL


def _google_challenge_url(url: str) -> bool:
    lower = (url or "").lower()
    if "accounts.google.com" not in lower:
        return False
    if "/challenge" in lower or "signin/v2/challenge" in lower:
        return True
    if "twosv" in lower or "two-step" in lower:
        return True
    return False


async def _page_text_lower(page) -> str:
    try:
        body = await page.locator("body").inner_text(timeout=5000)
        return (body or "").lower()
    except Exception:
        return ""


async def _detect_studio_challenge(page, platform: StudioPlatform) -> bool:
    url = page.url or ""
    if platform == "youtube" and _google_challenge_url(url):
        return True
    text = await _page_text_lower(page)
    markers = (
        "2-step verification",
        "verify it's you",
        "verification code",
        "enter the code",
        "captcha",
        "unusual traffic",
    )
    return any(m in text for m in markers)


async def _try_google_identifier(page, login_id: str) -> bool:
    if not login_id:
        return False
    from app.behavior.warmup_playwright import _human_type_locator

    selectors = (
        'input[type="email"]',
        "#identifierId",
        'input[name="identifier"]',
    )
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            if await loc.count() == 0:
                continue
            await loc.wait_for(state="visible", timeout=_STEP_WAIT_MS)
            await _human_type_locator(page, loc, login_id)
            next_btn = page.get_by_role("button", name="Next")
            if await next_btn.count():
                await next_btn.first.click(timeout=_STEP_WAIT_MS)
            else:
                await page.keyboard.press("Enter")
            await asyncio.sleep(2.0)
            return True
        except Exception:
            continue
    return False


async def _try_google_password(page, password: str) -> bool:
    if not password:
        return False
    from app.behavior.warmup_playwright import _human_type_locator

    selectors = (
        'input[type="password"]',
        'input[name="Passwd"]',
        'input[name="password"]',
    )
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            if await loc.count() == 0:
                continue
            await loc.wait_for(state="visible", timeout=_STEP_WAIT_MS)
            await _human_type_locator(page, loc, password)
            next_btn = page.get_by_role("button", name="Next")
            if await next_btn.count():
                await next_btn.first.click(timeout=_STEP_WAIT_MS)
            else:
                await page.keyboard.press("Enter")
            await asyncio.sleep(3.0)
            return True
        except Exception:
            continue
    return False


async def _try_tiktok_login(page, login_id: str, password: str) -> bool:
    if not login_id or not password:
        return False
    try:
        user = page.locator('input[name="username"], input[placeholder*="mail"], input[type="text"]').first
        await user.wait_for(state="visible", timeout=_STEP_WAIT_MS)
        await user.fill(login_id)
        pwd = page.locator('input[type="password"]').first
        await pwd.fill(password)
        submit = page.get_by_role("button", name="Log in")
        if await submit.count():
            await submit.first.click()
        else:
            await page.keyboard.press("Enter")
        await asyncio.sleep(3.0)
        return True
    except Exception as exc:
        logger.warning("studio.tiktok_autofill_failed", error=str(exc))
        return False


async def _persist_context_state(username: str, context, platform: str) -> bool:
    try:
        state = await context.storage_state()
        save_playwright_state(username, state, platform)
        return True
    except Exception as exc:
        logger.error("studio.save_state_failed", username=username, error=str(exc))
        return False


async def _async_studio_login(
    *,
    username: str,
    password: str,
    proxy_url: str,
    platform: StudioPlatform,
    login_identifier: str | None = None,
    locale: str = "en-US",
    timezone_id: str = "UTC",
    proxy_country: str | None = None,
    headless: bool = True,
    on_status: StatusCallback | None = None,
) -> StudioLoginResult:
    def ping(title: str, detail: str | None = None) -> None:
        if on_status:
            on_status(title, detail)

    if not (proxy_url or "").strip():
        return StudioLoginResult(ok=False, error="нужен прокси")

    if studio_session_ready(username, platform):
        return StudioLoginResult(ok=True, page_url=_studio_url(platform))

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        return StudioLoginResult(ok=False, error=f"playwright не установлен: {exc}")

    state_file = playwright_state_path(username, platform)
    storage = str(state_file) if state_file.exists() else None
    proxy = _parse_proxy(proxy_url)
    login_id = (login_identifier or "").strip()

    ping("Headless", f"Chromium → {platform} Studio")
    async with async_playwright() as p:
        browser = await p.chromium.launch(**_studio_chromium_launch_kwargs(headless=headless, proxy=proxy))
        try:
            profile = ensure_studio_desktop_profile(
                username, platform, proxy_country=proxy_country
            )
            context = await browser.new_context(
                **studio_playwright_context_kwargs(
                    profile,
                    timezone_id=timezone_id,
                    storage_state_path=storage,
                )
            )
            page = await context.new_page()
            target = _studio_url(platform)
            ping("Headless", "открываю Studio")
            await page.goto(target, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
            await asyncio.sleep(2.0)

            if studio_session_ready(username, platform):
                await _persist_context_state(username, context, platform)
                return StudioLoginResult(ok=True, page_url=page.url)

            if await _detect_studio_challenge(page, platform):
                ping("Challenge", "нужно подтверждение (2FA / CAPTCHA)")
                return StudioLoginResult(ok=False, challenge=True, page_url=page.url)

            needs_login = platform == "youtube" and "accounts.google.com" in (page.url or "")
            if platform == "tiktok":
                needs_login = needs_login or await page.locator('input[type="password"]').count() > 0

            if needs_login and login_id and password:
                ping("Headless", "ввожу логин и пароль")
                if platform == "youtube":
                    await _try_google_identifier(page, login_id)
                    if await _detect_studio_challenge(page, platform):
                        ping("Challenge", "Google запросил подтверждение")
                        return StudioLoginResult(ok=False, challenge=True, page_url=page.url)
                    await _try_google_password(page, password)
                else:
                    await _try_tiktok_login(page, login_id, password)

                await asyncio.sleep(2.0)
                if platform == "youtube" and "studio.youtube.com" not in (page.url or ""):
                    try:
                        await page.goto(target, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
                        await asyncio.sleep(2.0)
                    except Exception:
                        pass

            await _persist_context_state(username, context, platform)
            if studio_session_ready(username, platform):
                return StudioLoginResult(ok=True, page_url=page.url)

            if await _detect_studio_challenge(page, platform):
                return StudioLoginResult(ok=False, challenge=True, page_url=page.url)

            if needs_login:
                return StudioLoginResult(
                    ok=False,
                    challenge=True,
                    error="Требуется подтверждение (2FA / CAPTCHA) или ручной вход",
                    page_url=page.url,
                )
            return StudioLoginResult(
                ok=False,
                error="Studio cookies не появились после входа",
                page_url=page.url,
            )
        finally:
            await browser.close()


def studio_login(
    *,
    username: str,
    password: str,
    proxy_url: str,
    platform: StudioPlatform,
    login_identifier: str | None = None,
    locale: str = "en_US",
    timezone_id: str = "UTC",
    proxy_country: str | None = None,
    headless: bool | None = None,
    on_status: StatusCallback | None = None,
) -> StudioLoginResult:
    """Synchronous headless Studio login."""
    if not playwright_browsers_available():
        return StudioLoginResult(ok=False, error="Chromium не установлен")
    headless = settings.playwright_headless if headless is None else headless
    try:
        return asyncio.run(
            _async_studio_login(
                username=username,
                password=password,
                proxy_url=proxy_url,
                platform=platform,
                login_identifier=login_identifier,
                locale=locale.replace("_", "-"),
                timezone_id=timezone_id,
                proxy_country=proxy_country,
                headless=headless,
                on_status=on_status,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("studio.login_failed", username=username, platform=platform, error=str(exc))
        return StudioLoginResult(ok=False, error=str(exc))


async def _async_probe_studio_session_liveness(
    *,
    username: str,
    proxy_url: str,
    platform: StudioPlatform,
    locale: str = "en-US",
    timezone_id: str = "UTC",
    proxy_country: str | None = None,
    headless: bool = True,
) -> StudioLivenessResult:
    if not studio_session_ready(username, platform):
        return StudioLivenessResult(ok=False, error="Cookies Studio на диске не найдены")
    if not (proxy_url or "").strip():
        return StudioLivenessResult(ok=False, error="нужен прокси")
    if not playwright_browsers_available():
        return StudioLivenessResult(ok=False, error="Chromium не установлен")

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        return StudioLivenessResult(ok=False, error=f"playwright не установлен: {exc}")

    state_file = playwright_state_path(username, platform)
    storage = str(state_file) if state_file.exists() else None
    proxy = _parse_proxy(proxy_url)
    target = _studio_url(platform)

    async with async_playwright() as p:
        browser = await p.chromium.launch(**_studio_chromium_launch_kwargs(headless=headless, proxy=proxy))
        try:
            profile = ensure_studio_desktop_profile(
                username, platform, proxy_country=proxy_country
            )
            context = await browser.new_context(
                **studio_playwright_context_kwargs(
                    profile,
                    timezone_id=timezone_id,
                    storage_state_path=storage,
                )
            )
            page = await context.new_page()
            await page.goto(target, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
            await asyncio.sleep(2.0)
            challenge = await _detect_studio_challenge(page, platform)
            needs_login = platform == "youtube" and "accounts.google.com" in (page.url or "")
            if platform == "tiktok":
                needs_login = needs_login or await page.locator('input[type="password"]').count() > 0
            return evaluate_studio_liveness(
                page_url=page.url or "",
                platform=platform,
                needs_login=needs_login,
                challenge=challenge,
            )
        finally:
            await browser.close()


def _run_probe_coroutine(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def probe_studio_session_liveness(
    *,
    username: str,
    proxy_url: str,
    platform: StudioPlatform,
    locale: str = "en_US",
    timezone_id: str = "UTC",
    proxy_country: str | None = None,
    headless: bool | None = None,
) -> StudioLivenessResult:
    """Open Studio with stored Playwright state and detect login/challenge redirects."""
    headless = settings.playwright_headless if headless is None else headless
    try:
        return _run_probe_coroutine(
            _async_probe_studio_session_liveness(
                username=username,
                proxy_url=proxy_url,
                platform=platform,
                locale=locale.replace("_", "-"),
                timezone_id=timezone_id,
                proxy_country=proxy_country,
                headless=headless,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "studio.liveness_probe_failed",
            username=username,
            platform=platform,
            error=str(exc),
        )
        return StudioLivenessResult(ok=False, error=str(exc))
