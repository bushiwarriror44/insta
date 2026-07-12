"""Heavy warmup / first-login via stealth Playwright.

The instagrapi private-API path is great for posting but its first
login can trip soft-checkpoints, especially on fresh accounts. A real
browser session, fingerprinted to match the device geo, makes the first
auth handshake much more believable.

Use this module:
- For a brand-new account: run :func:`first_login` once, persist storage
  state, then resume API logins normally.
- For unstuck checkpoints: open the account in browser to acknowledge a
  warning manually.
- As periodic background warmup (~ once every N days).

The Playwright runtime is optional at import time so workers without it
keep functioning. Install with ``pip install playwright && playwright
install chromium``.

Anti-detection notes:
    * The browser ``user_agent`` and ``viewport`` are derived from the
      account's persistent device fingerprint when available — the same
      device that the API path advertises, just expressed as a mobile
      Chrome UA. That keeps server-side device-graph correlation honest.
    * ``page.fill`` is replaced with ``page.locator(...).type(text,
      delay=…)`` so each character has a randomised inter-keystroke
      delay (50–180 ms), and we click the input first so focus events
      look organic.
    * Cookie / "Allow all" banners are accepted in a best-effort try
      block — IG and Meta family banners differ across locales.
    * Headful mode is opt-in via ``PLAYWRIGHT_HEADLESS=false`` for
      manual on-the-spot checkpoint resolution.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.accounts.playwright_session import sessionid_from_playwright_state_data
from app.accounts.session_cookie import sessionid_from_cookies_array
from app.config import settings
from app.geo.timezone_normalize import normalize_playwright_timezone
from app.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class FirstLoginResult:
    ok: bool
    challenge: bool = False
    error: str | None = None
    session_id: str | None = None
    cookie_names: tuple[str, ...] = ()


def _storage_dir(username: str) -> Path:
    path = settings.playwright_dir / username
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Fingerprint → browser parameter helpers.
# ---------------------------------------------------------------------------


def _ua_for_device(device_settings: dict | None, fallback_ua: str | None) -> str:
    """Build a mobile Chrome UA aligned with the persistent Android device.

    Instagrapi's UA is the *Instagram app* UA — for Playwright we need the
    *browser* UA on the same Android version. Reusing the device's Android
    version + manufacturer keeps fingerprints consistent across surfaces.
    """
    if device_settings:
        android_release = device_settings.get("android_release", "13")
        model = device_settings.get("model", "SM-S908B")
        # Pin a recent stable mobile Chrome major; rotated occasionally per call
        # to avoid a single static UA across all sessions.
        chrome_majors = ["122.0.6261.105", "124.0.6367.171", "125.0.6422.165", "126.0.6478.122"]
        chrome_major = random.choice(chrome_majors)
        return (
            f"Mozilla/5.0 (Linux; Android {android_release}; {model}) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{chrome_major} Mobile Safari/537.36"
        )
    if fallback_ua:
        return fallback_ua
    return (
        "Mozilla/5.0 (Linux; Android 13; SM-S908B) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.6367.171 Mobile Safari/537.36"
    )


def _viewport_from_resolution(resolution: str | None) -> dict[str, int]:
    """Convert a device resolution like ``1080x2400`` into a CSS viewport.

    Android-mobile DIP scales the physical resolution by the device pixel
    ratio (typically 2.5–3.5 for modern phones). Dividing by ~2.6 gives a
    realistic CSS viewport that pairs with ``device_scale_factor=3``.
    """
    if resolution and "x" in resolution:
        try:
            w, h = resolution.lower().split("x", 1)
            width = max(320, int(int(w) / 2.625))
            height = max(640, int(int(h) / 2.625))
            return {"width": width, "height": height}
        except Exception:
            pass
    return {"width": 412, "height": 915}


_PROXY_REGEX = re.compile(r"^(?P<scheme>[a-zA-Z]+)://(?:(?P<user>[^:@]+)(?::(?P<pwd>[^@]*))?@)?(?P<host>.+)$")


def _parse_proxy(proxy_url: str) -> Optional[dict[str, str]]:
    """Convert ``http://user:pass@host:port`` to Playwright's proxy dict."""
    if not proxy_url:
        return None
    match = _PROXY_REGEX.match(proxy_url.strip())
    if not match:
        return {"server": proxy_url}
    result: dict[str, str] = {
        "server": f"{match.group('scheme')}://{match.group('host')}",
    }
    user = match.group("user")
    pwd = match.group("pwd")
    if user:
        result["username"] = user
    if pwd:
        result["password"] = pwd
    return result


# ---------------------------------------------------------------------------
# Humanizer helpers running inside the Playwright async loop.
# ---------------------------------------------------------------------------


async def _human_wait(low: float, high: float) -> None:
    delay = random.uniform(low, high)
    await asyncio.sleep(delay)


async def _human_type(page, selector: str, text: str, *, click_first: bool = True) -> None:
    """Type into a field with mouse focus + per-keystroke delay."""
    locator = page.locator(selector)
    await locator.wait_for(state="visible", timeout=15000)
    if click_first:
        try:
            box = await locator.bounding_box()
            if box:
                target_x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
                target_y = box["y"] + box["height"] * random.uniform(0.3, 0.7)
                await page.mouse.move(target_x, target_y, steps=random.randint(8, 20))
                await page.mouse.down()
                await asyncio.sleep(random.uniform(0.04, 0.12))
                await page.mouse.up()
        except Exception:  # noqa: BLE001 - mouse path is purely cosmetic
            pass
    await locator.click(timeout=5000)
    await _human_wait(0.2, 0.6)
    await locator.type(text, delay=random.randint(50, 180))


async def _human_type_first_match(page, selectors: list[str], text: str, *, click_first: bool = True) -> str:
    """Type into the first visible field matching any *selectors*."""
    last_exc: Exception | None = None
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if await loc.count() == 0:
                continue
            await _human_type(page, selector, text, click_first=click_first)
            return selector
        except Exception as exc:
            last_exc = exc
            continue
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("login form fields not found")


async def _first_visible_selector(page, selectors: list[str]) -> str | None:
    for selector in selectors:
        try:
            if await page.locator(selector).first.count() > 0:
                return selector
        except Exception:
            continue
    return None


async def _accept_cookie_banner(page) -> None:
    """Best-effort accept of Meta / Instagram consent banners."""
    selectors = [
        'button:has-text("Allow all cookies")',
        'button:has-text("Allow all")',
        'button:has-text("Allow essential and optional cookies")',
        'button:has-text("Accept all")',
        'button:has-text("Akzeptieren")',
        'button:has-text("Alle akzeptieren")',
        'button:has-text("Принять")',
        'button:has-text("Принять все")',
        'button:has-text("Aceptar")',
        'button:has-text("Aceptar todo")',
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                await loc.click(timeout=3000)
                await _human_wait(0.5, 1.4)
                return
        except Exception:
            continue


async def _human_scroll(page, total_scrolls: int = 5) -> None:
    for _ in range(total_scrolls):
        delta = random.randint(400, 1100)
        # Slight horizontal drift to mimic real-finger scrolls.
        try:
            await page.mouse.move(
                random.randint(80, 320),
                random.randint(200, 700),
                steps=random.randint(4, 12),
            )
        except Exception:
            pass
        await page.mouse.wheel(0, delta)
        await _human_wait(1.0, 3.0)


async def _try_submit_totp(page, totp_seed: str | None) -> bool:
    """Fill Instagram 2FA code when a TOTP seed is configured."""
    if not (totp_seed or "").strip():
        return False
    selectors = [
        'input[name="verificationCode"]',
        'input[aria-label*="code" i]',
        'input[autocomplete="one-time-code"]',
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() == 0:
                continue
            try:
                import pyotp

                code = pyotp.TOTP(totp_seed.strip().replace(" ", "")).now()
            except Exception as exc:
                logger.warning("playwright.totp_failed", error=str(exc))
                return False
            await _human_type(page, sel, code, click_first=True)
            await _human_wait(0.5, 1.2)
            confirm = page.locator('button[type="submit"]').first
            if await confirm.count() > 0:
                await confirm.click()
            await _human_wait(4.0, 7.0)
            return True
        except Exception:
            continue
    return False


async def _detect_challenge(page) -> bool:
    challenge_selectors = [
        "text=Suspicious Login",
        "text=We Detected An Unusual Login Attempt",
        "text=Help us confirm",
        "text=Confirm it's you",
        "text=checkpoint",
        'input[name="security_code"]',
        'input[name="email_confirmation_code"]',
        'input[aria-label*="security code" i]',
    ]
    for sel in challenge_selectors:
        try:
            if await page.locator(sel).count() > 0:
                return True
        except Exception:
            pass
    return False


async def _detect_login_error(page) -> str | None:
    """Return a human-readable login error when IG shows one on the page."""
    error_selectors = [
        "text=Sorry, your password was incorrect",
        "text=The password you entered is incorrect",
        "text=The username you entered doesn't belong to an account",
        "text=There was a problem logging you into Instagram",
        "text=Please check your username and try again",
        "text=incorrect password",
        "text=Неверный пароль",
        "text=Couldn't log in",
    ]
    for sel in error_selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                text = (await loc.inner_text()).strip()
                if text:
                    return text
                return sel.replace("text=", "")
        except Exception:
            continue
    return None


async def _detect_2fa_required(page) -> bool:
    selectors = [
        'input[name="verificationCode"]',
        'input[aria-label*="code" i]',
        'input[autocomplete="one-time-code"]',
        "text=Two-factor authentication",
        "text=Enter the 6-digit code",
        "text=security code",
    ]
    for sel in selectors:
        try:
            if await page.locator(sel).count() > 0:
                return True
        except Exception:
            continue
    return False


_INSTAGRAM_URL = "https://www.instagram.com"
_INSTAGRAM_LOGIN_URL = "https://www.instagram.com/accounts/login/"
_SESSIONID_POLL_TIMEOUT_SEC = 60.0
_USERNAME_SELECTORS = [
    'input[name="username"]',
    'input[aria-label*="username" i]',
    'input[aria-label*="phone" i]',
    'input[aria-label*="email" i]',
    'input[autocomplete="username"]',
]
_PASSWORD_SELECTORS = [
    'input[name="password"]',
    'input[aria-label*="password" i]',
    'input[type="password"]',
    'input[autocomplete="current-password"]',
]


def _instagram_sessionid_from_cookies(cookies: list) -> str | None:
    """Return validated Instagram sessionid from Playwright cookie dicts."""
    return sessionid_from_cookies_array(cookies)


def _cookie_names(cookies: list) -> tuple[str, ...]:
    names: list[str] = []
    for item in cookies:
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str) and name:
                names.append(name)
    return tuple(sorted(set(names)))


async def _gather_instagram_cookies(context) -> list:
    """Collect cookies from all Instagram origins in the browser context."""
    seen: set[tuple[str, str]] = set()
    merged: list = []
    url_candidates = (
        None,
        _INSTAGRAM_URL,
        "https://instagram.com",
        "https://i.instagram.com",
    )
    for url in url_candidates:
        try:
            cookies = await context.cookies(url) if url else await context.cookies()
        except Exception:
            continue
        for item in cookies:
            if not isinstance(item, dict):
                continue
            key = (str(item.get("name", "")), str(item.get("domain", "")))
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


async def _sessionid_from_saved_storage(context, state_file: Path) -> str | None:
    """Persist storage state and extract sessionid (covers HttpOnly cookies)."""
    try:
        await context.storage_state(path=str(state_file))
        data = json.loads(state_file.read_text(encoding="utf-8"))
        return sessionid_from_playwright_state_data(data)
    except Exception:
        return None


async def _resolve_instagram_sessionid(
    context,
    page,
    state_file: Path,
    *,
    timeout_sec: float = _SESSIONID_POLL_TIMEOUT_SEC,
) -> tuple[str | None, tuple[str, ...]]:
    """Poll cookies and storage state until sessionid appears or timeout."""
    deadline = time.monotonic() + timeout_sec
    last_names: tuple[str, ...] = ()
    nav_targets = (
        _INSTAGRAM_URL,
        f"{_INSTAGRAM_URL}/explore/",
        f"{_INSTAGRAM_URL}/accounts/onetap/",
    )
    nav_index = 0

    while time.monotonic() < deadline:
        if await _detect_challenge(page):
            return None, last_names

        login_error = await _detect_login_error(page)
        if login_error:
            logger.warning("playwright.login_error_text", error=login_error, url=page.url)
            return None, last_names

        await _dismiss_post_login_modals(page)

        cookies = await _gather_instagram_cookies(context)
        last_names = _cookie_names(cookies)
        session_id = _instagram_sessionid_from_cookies(cookies)
        if session_id:
            return session_id, last_names

        session_id = await _sessionid_from_saved_storage(context, state_file)
        if session_id:
            return session_id, last_names

        try:
            target = nav_targets[nav_index % len(nav_targets)]
            nav_index += 1
            if target not in page.url:
                await page.goto(target, wait_until="domcontentloaded", timeout=25000)
        except Exception:
            pass

        await asyncio.sleep(random.uniform(0.8, 1.6))

    return None, last_names


async def _dismiss_post_login_modals(page) -> None:
    """Best-effort dismiss of post-login prompts (save login, notifications, etc.)."""
    selectors = [
        'button:has-text("Not Now")',
        'button:has-text("Not now")',
        'button:has-text("Не сейчас")',
        'button:has-text("Nicht jetzt")',
        'button:has-text("Ahora no")',
        'button:has-text("Save info")',
        'button:has-text("Save Information")',
        'button:has-text("Сохранить данные")',
        'button:has-text("Turn on Notifications")',
        'div[role="button"]:has-text("Not Now")',
        'div[role="button"]:has-text("Not now")',
        '[role="button"]:has-text("Not Now")',
        '[role="button"]:has-text("Not now")',
        'button:has-text("Continue")',
        'div[role="button"]:has-text("Continue")',
    ]
    for _ in range(3):
        clicked = False
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    await loc.click(timeout=3000)
                    await _human_wait(0.4, 1.0)
                    clicked = True
            except Exception:
                continue
        if not clicked:
            break


async def _is_logged_in(context, page) -> bool:
    """True when sessionid cookie exists or login form is gone with nav visible."""
    cookies = await _gather_instagram_cookies(context)
    if _instagram_sessionid_from_cookies(cookies):
        return True
    try:
        username_sel = await _first_visible_selector(page, _USERNAME_SELECTORS)
        if username_sel:
            return False
        nav_visible = await page.locator('a[href="/explore/"]').count() > 0
        home_visible = await page.locator('a[href="/"]').count() > 0
        return nav_visible or home_visible
    except Exception:
        return False


def playwright_browsers_available() -> bool:
    root = Path(settings.playwright_browsers_path if hasattr(settings, "playwright_browsers_path") else "/ms-playwright")
    import os
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", str(root)))
    try:
        return root.exists() and any(root.iterdir())
    except OSError:
        return False


async def _async_first_login(
    username: str,
    password: str,
    proxy_url: Optional[str],
    locale: str,
    timezone_id: str,
    user_agent: str,
    viewport: dict[str, int],
    headless: bool,
    totp_seed: Optional[str] = None,
) -> FirstLoginResult:
    if not (proxy_url or "").strip():
        logger.error("playwright.proxy_required", username=username)
        return FirstLoginResult(ok=False, error="proxy required")

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover
        logger.error("playwright.not_installed", error=str(exc))
        return FirstLoginResult(ok=False, error="playwright not installed")

    # `playwright-stealth` 2.x exposes a different API than 1.x. Try both.
    stealth_apply = None
    try:
        from playwright_stealth import Stealth  # type: ignore

        stealth_instance = Stealth()

        async def _apply(page):
            await stealth_instance.apply_stealth_async(page)

        stealth_apply = _apply
    except ImportError:
        try:
            from playwright_stealth import stealth_async  # type: ignore

            stealth_apply = stealth_async  # legacy 1.x path
        except ImportError:  # pragma: no cover
            logger.warning("playwright_stealth.not_installed")

    storage = _storage_dir(username)
    state_file = storage / "state.json"

    proxy_arg = _parse_proxy(proxy_url) if proxy_url else None

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
            proxy=proxy_arg,
        )
        context_kwargs = {
            "locale": locale,
            "timezone_id": timezone_id,
            "user_agent": user_agent,
            "viewport": viewport,
            "device_scale_factor": 3,
            "has_touch": True,
            "is_mobile": True,
        }
        if state_file.exists():
            context_kwargs["storage_state"] = str(state_file)

        context = await browser.new_context(**context_kwargs)

        page = await context.new_page()
        if stealth_apply is not None:
            try:
                await stealth_apply(page)
            except Exception as exc:  # pragma: no cover
                logger.warning("playwright.stealth_failed", error=str(exc))

        try:
            await page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:
            logger.error("playwright.goto_failed", error=str(exc))
            await context.close()
            await browser.close()
            return FirstLoginResult(ok=False, error=str(exc))

        await _human_wait(2.0, 4.0)
        await _accept_cookie_banner(page)
        await _human_wait(0.6, 1.4)

        already_logged_in = await _is_logged_in(context, page)
        if not already_logged_in:
            try:
                if "accounts/login" not in page.url:
                    await page.goto(
                        _INSTAGRAM_LOGIN_URL,
                        wait_until="domcontentloaded",
                        timeout=45000,
                    )
                    await _human_wait(1.0, 2.0)
                    await _accept_cookie_banner(page)

                await _human_type_first_match(page, _USERNAME_SELECTORS, username)
                await _human_wait(0.7, 1.6)
                await _human_type_first_match(
                    page, _PASSWORD_SELECTORS, password, click_first=False
                )
                await _human_wait(0.7, 1.6)
                submit_sel = await _first_visible_selector(
                    page,
                    ['button[type="submit"]', 'button:has-text("Log in")', 'button:has-text("Log In")'],
                )
                if submit_sel is None:
                    raise RuntimeError("login submit button not found")
                submit = page.locator(submit_sel).first
                box = await submit.bounding_box()
                if box:
                    cx = box["x"] + box["width"] / 2
                    cy = box["y"] + box["height"] / 2
                    await page.mouse.move(cx, cy, steps=random.randint(8, 18))
                    await asyncio.sleep(random.uniform(0.1, 0.3))
                await submit.click()
            except Exception as exc:
                logger.error("playwright.login_form_failed", username=username, error=str(exc))
                await context.close()
                await browser.close()
                return FirstLoginResult(ok=False, error=str(exc))

            await _human_wait(3.0, 6.0)
            try:
                await page.wait_for_function(
                    "() => !window.location.pathname.includes('/accounts/login')",
                    timeout=25000,
                )
            except Exception:
                pass

            await _try_submit_totp(page, totp_seed)
            await _human_wait(3.0, 6.0)
            await _dismiss_post_login_modals(page)

            login_error = await _detect_login_error(page)
            if login_error:
                await context.storage_state(path=str(state_file))
                await context.close()
                await browser.close()
                return FirstLoginResult(ok=False, error=login_error)

            if await _detect_2fa_required(page) and not (totp_seed or "").strip():
                await context.storage_state(path=str(state_file))
                await context.close()
                await browser.close()
                return FirstLoginResult(
                    ok=False,
                    error="Требуется 2FA — укажите TOTP seed в настройках аккаунта",
                )

            if await _detect_challenge(page):
                logger.warning("playwright.challenge_detected", username=username)
                await context.storage_state(path=str(state_file))
                await context.close()
                await browser.close()
                return FirstLoginResult(ok=False, challenge=True, error="challenge required")

        await _human_wait(1.0, 2.0)
        await _dismiss_post_login_modals(page)
        await _human_scroll(page, total_scrolls=random.randint(2, 4))

        session_id, cookie_names = await _resolve_instagram_sessionid(context, page, state_file)
        if not session_id:
            logger.error(
                "playwright.sessionid_missing",
                username=username,
                cookie_names=list(cookie_names),
                page_url=page.url,
            )
            await context.storage_state(path=str(state_file))
            await context.close()
            await browser.close()
            if await _detect_challenge(page):
                return FirstLoginResult(
                    ok=False,
                    challenge=True,
                    error="challenge required",
                    cookie_names=cookie_names,
                )
            login_error = await _detect_login_error(page)
            if login_error:
                return FirstLoginResult(ok=False, error=login_error, cookie_names=cookie_names)
            if cookie_names:
                preview = ", ".join(cookie_names[:10])
                suffix = f" (+{len(cookie_names) - 10})" if len(cookie_names) > 10 else ""
                err = (
                    f"Instagram не выдал sessionid (cookies: {preview}{suffix}). "
                    "Проверьте пароль, 2FA или challenge"
                )
            else:
                err = "Instagram не выдал sessionid — проверьте пароль, 2FA или challenge"
            return FirstLoginResult(ok=False, error=err, cookie_names=cookie_names)

        await context.storage_state(path=str(state_file))
        await context.close()
        await browser.close()

    logger.info("playwright.first_login_done", username=username, storage=str(state_file))
    return FirstLoginResult(ok=True, session_id=session_id, cookie_names=cookie_names)


def first_login(
    username: str,
    password: str,
    proxy_url: Optional[str],
    locale: str = "en_US",
    timezone_id: str = "UTC",
    user_agent: Optional[str] = None,
    viewport: Optional[dict[str, int]] = None,
    headless: Optional[bool] = None,
    fingerprint=None,
    totp_seed: Optional[str] = None,
) -> FirstLoginResult:
    """Synchronous wrapper around the async stealth login.

    If ``fingerprint`` (a :class:`~app.accounts.device_factory.DeviceFingerprint`)
    is supplied, ``user_agent`` and ``viewport`` are derived from it for
    consistency with the API path. Explicit kwargs win over fingerprint
    derivation.
    """
    proxy_url = (proxy_url or "").strip()
    if not proxy_url:
        logger.error("playwright.proxy_required", username=username)
        return FirstLoginResult(ok=False, error="proxy required")

    device_settings = None
    fp_locale = None
    if fingerprint is not None:
        try:
            device_settings = fingerprint.settings.get("device_settings")
            fp_locale = fingerprint.locale
        except AttributeError:
            device_settings = None

    if user_agent is None:
        user_agent = _ua_for_device(device_settings, fallback_ua=None)
    if viewport is None:
        resolution = (device_settings or {}).get("resolution")
        viewport = _viewport_from_resolution(resolution)

    if locale == "en_US" and fp_locale:
        locale = fp_locale

    headless = settings.playwright_headless if headless is None else headless

    timezone_id = normalize_playwright_timezone(timezone_id)

    try:
        return asyncio.run(
            _async_first_login(
                username=username,
                password=password,
                proxy_url=proxy_url,
                locale=locale.replace("_", "-"),
                timezone_id=timezone_id,
                user_agent=user_agent,
                viewport=viewport,
                headless=headless,
                totp_seed=totp_seed,
            )
        )
    except Exception as exc:  # noqa: BLE001 - surface Playwright failures to caller
        logger.error("playwright.first_login_failed", username=username, error=str(exc))
        return FirstLoginResult(ok=False, error=str(exc))
