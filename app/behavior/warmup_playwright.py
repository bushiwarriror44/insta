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
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.config import settings
from app.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class FirstLoginResult:
    ok: bool
    challenge: bool = False
    error: str | None = None


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
        manufacturer = device_settings.get("manufacturer", "samsung")
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
        'input[name="security_code"]',
    ]
    for sel in challenge_selectors:
        try:
            if await page.locator(sel).count() > 0:
                return True
        except Exception:
            pass
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

        already_logged_in = await page.locator('a[href="/explore/"]').count() > 0
        if not already_logged_in:
            try:
                await _human_type(page, 'input[name="username"]', username)
                await _human_wait(0.7, 1.6)
                await _human_type(page, 'input[name="password"]', password, click_first=False)
                await _human_wait(0.7, 1.6)
                # Move to submit and click with a tiny offset for realism.
                submit = page.locator('button[type="submit"]').first
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
            await _try_submit_totp(page, totp_seed)
            await _human_wait(3.0, 6.0)

            if await _detect_challenge(page):
                logger.warning("playwright.challenge_detected", username=username)
                await context.storage_state(path=str(state_file))
                await context.close()
                await browser.close()
                return FirstLoginResult(ok=False, challenge=True, error="challenge required")

        try:
            await page.goto("https://www.instagram.com/explore/", wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        await _human_wait(2.0, 4.0)
        await _human_scroll(page, total_scrolls=random.randint(3, 6))

        await context.storage_state(path=str(state_file))
        await context.close()
        await browser.close()

    logger.info("playwright.first_login_done", username=username, storage=str(state_file))
    return FirstLoginResult(ok=True)


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
