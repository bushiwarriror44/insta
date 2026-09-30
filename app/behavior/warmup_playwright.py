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
    * Playwright's ``--enable-automation`` flag is stripped via
      ``ignore_default_args``; ``navigator.webdriver`` is patched in a
      context init script and via ``playwright-stealth``.
    * Login goes directly to ``/accounts/login/`` with pre-login mouse
      jitter, human keystroke delays, and a real mouse click on submit
      (never Enter-only submit).
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

from app.behavior.playwright_surface import (
    LoginSurface,
    browser_launch_args,
    mouse_jitter_bounds,
    playwright_context_kwargs,
    stealth_init_script,
)

from app.accounts.playwright_session import (
    sessionid_from_playwright_state,
    sessionid_from_playwright_state_data,
    storage_state_has_session,
)
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
    login_debug_saved: bool = False
    page_url: str | None = None


def _storage_dir(username: str) -> Path:
    path = settings.playwright_dir / username
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Fingerprint → browser parameter helpers.
# ---------------------------------------------------------------------------

# Match Playwright Chromium 130+; 122–126 UA against Chromium 130 left Instagram
# on the Meta splash without a login form.
_CHROME_MAJORS = [
    "130.0.6723.117",
    "131.0.6778.140",
    "135.0.7049.95",
    "140.0.7339.81",
]
_CHROME_FALLBACK = _CHROME_MAJORS[0]

def _ua_for_device(device_settings: dict | None, fallback_ua: str | None) -> str:
    """Build a mobile Chrome UA aligned with the persistent Android device.

    Instagrapi's UA is the *Instagram app* UA — for Playwright we need the
    *browser* UA on the same Android version. Reusing the device's Android
    version + manufacturer keeps fingerprints consistent across surfaces.
    """
    if device_settings:
        android_release = device_settings.get("android_release", "13")
        model = device_settings.get("model", "SM-S908B")
        chrome_major = random.choice(_CHROME_MAJORS)
        return (
            f"Mozilla/5.0 (Linux; Android {android_release}; {model}) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{chrome_major} Mobile Safari/537.36"
        )
    if fallback_ua:
        return fallback_ua
    return (
        f"Mozilla/5.0 (Linux; Android 13; SM-S908B) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{_CHROME_FALLBACK} Mobile Safari/537.36"
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


def _desktop_ua() -> str:
    """Desktop Chrome UA — Instagram web login is more reliable than mobile."""
    chrome_major = random.choice(_CHROME_MAJORS)
    return (
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{chrome_major} Safari/537.36"
    )


def _desktop_viewport() -> dict[str, int]:
    return {"width": 1280, "height": 800}


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


def _accept_language_for_locale(locale: str) -> str:
    normalized = (locale or "en-US").replace("_", "-")
    base = normalized.split("-", 1)[0]
    return f"{normalized},{base};q=0.9"


async def _apply_stealth_context(context, surface: LoginSurface = "desktop") -> None:
    try:
        await context.add_init_script(stealth_init_script(surface))
    except Exception as exc:  # pragma: no cover
        logger.warning("playwright.stealth_context_failed", error=str(exc))


async def _human_mouse_jitter(
    page,
    *,
    moves: int | None = None,
    surface: LoginSurface = "desktop",
) -> None:
    max_x, max_y, min_x, min_y = mouse_jitter_bounds(surface)
    count = moves if moves is not None else random.randint(2, 5)
    for _ in range(count):
        try:
            await page.mouse.move(
                random.randint(min_x, max_x),
                random.randint(min_y, max_y),
                steps=random.randint(6, 18),
            )
            await asyncio.sleep(random.uniform(0.04, 0.14))
        except Exception:
            break


async def _human_click_locator(page, loc) -> None:
    box = await loc.bounding_box()
    if box:
        cx = box["x"] + box["width"] * random.uniform(0.25, 0.75)
        cy = box["y"] + box["height"] * random.uniform(0.25, 0.75)
        await page.mouse.move(cx, cy, steps=random.randint(10, 24))
        await asyncio.sleep(random.uniform(0.08, 0.22))
        await page.mouse.down()
        await asyncio.sleep(random.uniform(0.04, 0.12))
        await page.mouse.up()
        return
    await loc.click(timeout=5000, delay=random.randint(40, 120))


async def _simulate_pre_login_behavior(page, surface: LoginSurface = "desktop") -> None:
    await _human_mouse_jitter(page, surface=surface)
    if random.random() < 0.55:
        try:
            await page.mouse.wheel(0, random.randint(80, 260))
            await _human_wait(0.4, 1.0)
        except Exception:
            pass
    await _human_wait(0.6, 1.4)


async def _human_type_locator(page, loc, text: str) -> None:
    await _human_click_locator(page, loc)
    await _human_wait(0.2, 0.55)
    try:
        await loc.press("Control+A")
        await asyncio.sleep(random.uniform(0.05, 0.12))
        await loc.press("Backspace")
        await _human_wait(0.08, 0.22)
    except Exception:
        pass
    delay = random.randint(70, 170)
    await loc.press_sequentially(text, delay=delay)
    if len(text) > 8 and random.random() < 0.35:
        await _human_wait(0.15, 0.45)


async def _submit_login_form(page) -> None:
    await _human_wait(0.5, 1.2)
    submit_sel = await _first_visible_selector(
        page,
        [
            'button[type="submit"]',
            'button:has-text("Log in")',
            'button:has-text("Log In")',
            'div[role="button"]:has-text("Log in")',
            'div[role="button"]:has-text("Log In")',
        ],
    )
    if submit_sel is None:
        raise RuntimeError("login submit button not found")
    submit = page.locator(submit_sel).first
    await _human_click_locator(page, submit)
    await _human_wait(0.3, 0.7)


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


async def _login_field_locator(page, *, password: bool = False):
    """Return a Playwright locator for the username or password field."""
    selectors = _PASSWORD_SELECTORS if password else _USERNAME_SELECTORS
    labels = _PASSWORD_LABELS if password else _USERNAME_LABELS

    found = await _first_visible_selector(page, selectors)
    if found:
        loc = page.locator(found).first
        try:
            await loc.wait_for(state="visible", timeout=3000)
            return loc
        except Exception:
            pass

    for label in labels:
        try:
            loc = page.get_by_label(label, exact=False).first
            if await loc.count() > 0:
                await loc.wait_for(state="visible", timeout=3000)
                return loc
        except Exception:
            continue

    for label in labels:
        try:
            loc = page.get_by_placeholder(label, exact=False).first
            if await loc.count() > 0:
                await loc.wait_for(state="visible", timeout=3000)
                return loc
        except Exception:
            continue

    if not password:
        try:
            loc = page.get_by_role("textbox").first
            if await loc.count() > 0:
                await loc.wait_for(state="visible", timeout=3000)
                return loc
        except Exception:
            pass
    else:
        try:
            loc = page.get_by_role("textbox", name=re.compile("password|парол", re.I)).first
            if await loc.count() > 0:
                return loc
        except Exception:
            try:
                loc = page.locator('input[type="password"]').first
                if await loc.count() > 0:
                    return loc
            except Exception:
                pass

    return None


async def _login_form_visible(page) -> bool:
    return (await _login_field_locator(page, password=False)) is not None


async def _wait_login_inputs(page, timeout_ms: int) -> bool:
    """True when a username/email field becomes visible (splash has cleared)."""
    try:
        await page.wait_for_selector(
            'input[name="username"], input[name="email"], input[autocomplete="username"]',
            state="visible",
            timeout=max(1, timeout_ms),
        )
        return True
    except Exception:
        return False


async def _ensure_login_page(page, *, fast: bool = False) -> None:
    """Navigate to Instagram login and wait until the form is interactable."""
    goto_timeout = 25_000 if fast else 60_000
    wait_until = "commit" if fast else "load"
    post_nav_wait = (0.2, 0.5) if fast else (1.0, 2.0)
    link_wait = (0.2, 0.5) if fast else (1.0, 2.0)
    poll_sleep = 0.4 if fast else 0.8
    deadline_sec = 12.0 if fast else 60.0

    if "accounts/login" not in (page.url or ""):
        await page.goto(_INSTAGRAM_LOGIN_URL, wait_until=wait_until, timeout=goto_timeout)
    await _human_wait(*post_nav_wait)
    await _accept_cookie_banner(page)

    remaining_ms = int(max(1.0, deadline_sec) * 1000)
    if await _wait_login_inputs(page, min(remaining_ms, 45_000 if not fast else 8_000)):
        if await _login_form_visible(page):
            return

    deadline = time.monotonic() + deadline_sec
    while time.monotonic() < deadline:
        if await _login_form_visible(page):
            return
        for sel in _LOG_IN_LINK_SELECTORS:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    await loc.click(timeout=3000)
                    await _human_wait(*link_wait)
                    await _accept_cookie_banner(page)
                    break
            except Exception:
                continue
        if "accounts/login" not in (page.url or ""):
            try:
                await page.goto(
                    _INSTAGRAM_LOGIN_URL,
                    wait_until=wait_until,
                    timeout=goto_timeout if fast else 45_000,
                )
            except Exception:
                pass
        leftover_ms = int(max(0.0, deadline - time.monotonic()) * 1000)
        if leftover_ms > 500 and await _wait_login_inputs(page, min(leftover_ms, 8_000)):
            if await _login_form_visible(page):
                return
        await asyncio.sleep(poll_sleep)

    raise RuntimeError(
        f"login form fields not found (url={page.url!r}, title={await page.title()!r})"
    )


async def _fill_login_field(page, *, password: bool, text: str) -> None:
    """Fill a login field with mouse focus and human keystroke timing."""
    loc = await _login_field_locator(page, password=password)
    if loc is None:
        raise RuntimeError(
            f"login form fields not found (url={page.url!r}, title={await page.title()!r})"
        )
    await _human_type_locator(page, loc, text)


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


async def submit_verification_code(page, code: str) -> bool:
    """Type a 2FA/challenge/backup code into the active Instagram form."""
    normalized = (code or "").strip().replace(" ", "")
    if not normalized:
        return False
    selectors = [
        'input[name="verificationCode"]',
        'input[name="security_code"]',
        'input[name="email_confirmation_code"]',
        'input[aria-label*="code" i]',
        'input[autocomplete="one-time-code"]',
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() == 0:
                continue
            await _human_type(page, sel, normalized, click_first=True)
            await _human_wait(0.5, 1.2)
            confirm = page.locator('button[type="submit"]').first
            if await confirm.count() > 0:
                await confirm.click()
            else:
                await page.keyboard.press("Enter")
            await _human_wait(2.0, 4.0)
            return True
        except Exception:
            continue
    return False


async def _is_still_on_login_page(page) -> bool:
    url = (page.url or "").lower()
    if "accounts/login" in url:
        return True
    return await _login_form_visible(page)


async def _save_login_debug(page, username: str) -> bool:
    """Save a screenshot to help diagnose failed browser logins."""
    try:
        out = _storage_dir(username) / "login_debug.png"
        await page.screenshot(path=str(out), full_page=True)
        logger.info("playwright.login_debug_saved", username=username, path=str(out), url=page.url)
        return True
    except Exception as exc:
        logger.warning("playwright.login_debug_failed", username=username, error=str(exc))
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
        "text=We can't find an account",
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
    'input[name="email"]',
    'input[aria-label*="username" i]',
    'input[aria-label*="phone" i]',
    'input[aria-label*="email" i]',
    'input[aria-label*="логин" i]',
    'input[aria-label*="телефон" i]',
    'input[autocomplete="username"]',
    'form#loginForm input[type="text"]',
    '#loginForm input[type="text"]',
]
_PASSWORD_SELECTORS = [
    'input[name="password"]',
    'input[aria-label*="password" i]',
    'input[aria-label*="парол" i]',
    'input[type="password"]',
    'input[autocomplete="current-password"]',
    'form#loginForm input[type="password"]',
]
_USERNAME_LABELS = (
    "Phone number, username, or email",
    "Mobile number, username or email",
    "Phone number, username, or email address",
    "Номер телефона, имя пользователя или эл. адрес",
    "Telefonnummer, Benutzername oder E-Mail-Adresse",
)
_PASSWORD_LABELS = ("Password", "Пароль", "Passwort", "Contraseña")
_LOG_IN_LINK_SELECTORS = [
    'a[href="/accounts/login/"]',
    'a[href*="/accounts/login"]',
    'text=Log in',
    'text=Log In',
    'text=Войти',
    'text=Anmelden',
]


def _instagram_sessionid_from_cookies(cookies: list) -> str | None:
    """Return validated Instagram sessionid from Playwright cookie dicts."""
    return sessionid_from_cookies_array(cookies)


def _has_auth_cookies(cookies: list) -> bool:
    """True when Instagram auth cookies indicate a logged-in session."""
    for item in cookies:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        stripped = value.strip()
        if not stripped:
            continue
        if name == "sessionid" and len(stripped) >= 31:
            return True
        if name == "ds_user_id":
            return True
    return False


def _is_guest_browse_url(url: str) -> bool:
    path = (url or "").split("?", 1)[0].rstrip("/")
    return path in ("https://www.instagram.com", "https://www.instagram.com/explore")


def _guest_explore_error_message() -> str:
    return (
        "Вход не выполнен — открыт гостевой Explore без sessionid. "
        "Скорее всего неверный пароль или логин."
    )


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
) -> tuple[str | None, tuple[str, ...], bool]:
    """Poll cookies and storage state until sessionid appears or timeout.

    Returns ``(session_id, cookie_names, challenge)``. ``challenge`` is True when
    a checkpoint/challenge page was detected during the poll.
    """
    deadline = time.monotonic() + timeout_sec
    last_names: tuple[str, ...] = ()
    nav_targets = (
        f"{_INSTAGRAM_URL}/accounts/onetap/",
        _INSTAGRAM_URL,
        f"{_INSTAGRAM_URL}/explore/",
    )
    nav_index = 0

    while time.monotonic() < deadline:
        if await _detect_challenge(page):
            return None, last_names, True

        login_error = await _detect_login_error(page)
        if login_error:
            logger.warning("playwright.login_error_text", error=login_error, url=page.url)
            return None, last_names, False

        await _dismiss_post_login_modals(page)

        cookies = await _gather_instagram_cookies(context)
        last_names = _cookie_names(cookies)
        session_id = _instagram_sessionid_from_cookies(cookies)
        if session_id:
            return session_id, last_names, False

        session_id = await _sessionid_from_saved_storage(context, state_file)
        if session_id:
            return session_id, last_names, False

        try:
            target = nav_targets[nav_index % len(nav_targets)]
            nav_index += 1
            if target not in page.url:
                await page.goto(target, wait_until="domcontentloaded", timeout=25000)
        except Exception:
            pass

        await asyncio.sleep(random.uniform(0.8, 1.6))

    return None, last_names, False


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
    """True only when Instagram auth cookies (sessionid or ds_user_id) are present."""
    cookies = await _gather_instagram_cookies(context)
    return _has_auth_cookies(cookies)


def playwright_browsers_available() -> bool:
    root = Path(settings.playwright_browsers_path if hasattr(settings, "playwright_browsers_path") else "/ms-playwright")
    import os
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", str(root)))
    try:
        return root.exists() and any(root.iterdir())
    except OSError:
        return False


async def _try_resolve_email_challenge(
    page,
    *,
    email: Optional[str],
    email_password: Optional[str],
    imap_host: Optional[str],
    timeout_sec: int = 90,
) -> bool:
    if not (email or "").strip() or not (email_password or "").strip():
        return False
    import asyncio

    from app.accounts.email_handler import fetch_instagram_code

    code = await asyncio.to_thread(
        fetch_instagram_code,
        email.strip(),
        email_password.strip(),
        host=(imap_host or "").strip() or None,
        timeout_sec=timeout_sec,
    )
    if not code:
        return False
    if not await submit_verification_code(page, code):
        return False
    await _human_wait(3.0, 6.0)
    await _dismiss_post_login_modals(page)
    return not await _detect_challenge(page)


async def _async_first_login(
    username: str,
    password: str,
    proxy_url: Optional[str],
    locale: str,
    timezone_id: str,
    headless: bool,
    totp_seed: Optional[str] = None,
    login_identifier: Optional[str] = None,
    surface: LoginSurface = "mobile",
    fingerprint=None,
    email: Optional[str] = None,
    email_password: Optional[str] = None,
    imap_host: Optional[str] = None,
) -> FirstLoginResult:
    login_id = (login_identifier or username).strip()
    if not (proxy_url or "").strip():
        logger.error("playwright.proxy_required", username=username)
        return FirstLoginResult(ok=False, error="proxy required")

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover
        logger.error("playwright.not_installed", error=str(exc))
        return FirstLoginResult(ok=False, error="playwright not installed")

    # `playwright-stealth` 1.x exposes ``stealth_async``; 2.x uses ``Stealth``.
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
        except ImportError:  # pragma: no cover
            logger.warning("playwright_stealth.not_installed")

    storage = _storage_dir(username)
    state_file = storage / "state.json"
    login_debug_saved = False

    proxy_arg = _parse_proxy(proxy_url) if proxy_url else None

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            ignore_default_args=["--enable-automation"],
            args=browser_launch_args(surface),
            proxy=proxy_arg,
        )
        context_kwargs = playwright_context_kwargs(
            surface,
            fingerprint=fingerprint,
            locale=locale,
            timezone_id=timezone_id,
            storage_state_path=str(state_file)
            if state_file.exists() and storage_state_has_session(username)
            else None,
        )
        if state_file.exists() and not storage_state_has_session(username):
            logger.info("playwright.skip_guest_storage_state", username=username)

        context = await browser.new_context(**context_kwargs)
        await _apply_stealth_context(context, surface)

        page = await context.new_page()
        if stealth_apply is not None:
            try:
                await stealth_apply(page)
            except Exception as exc:  # pragma: no cover
                logger.warning("playwright.stealth_failed", error=str(exc))

        try:
            await page.goto(_INSTAGRAM_LOGIN_URL, wait_until="load", timeout=60000)
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
                await _ensure_login_page(page)
                await _simulate_pre_login_behavior(page, surface=surface)
                await _fill_login_field(page, password=False, text=login_id)
                await _human_wait(0.9, 2.0)
                await _fill_login_field(page, password=True, text=password)
                await _submit_login_form(page)
            except Exception as exc:
                logger.error("playwright.login_form_failed", username=username, error=str(exc))
                if await _save_login_debug(page, username):
                    login_debug_saved = True
                await context.close()
                await browser.close()
                return FirstLoginResult(
                    ok=False,
                    error=str(exc),
                    login_debug_saved=login_debug_saved,
                    page_url=page.url,
                )

            await _human_wait(3.0, 6.0)
            try:
                await page.wait_for_function(
                    "() => !window.location.pathname.includes('/accounts/login')",
                    timeout=25000,
                )
            except Exception:
                pass

            try:
                await page.goto(
                    f"{_INSTAGRAM_URL}/accounts/onetap/",
                    wait_until="domcontentloaded",
                    timeout=25000,
                )
                await _human_wait(2.0, 4.0)
                await _dismiss_post_login_modals(page)
            except Exception:
                pass

            await _try_submit_totp(page, totp_seed)
            await _human_wait(3.0, 6.0)
            await _dismiss_post_login_modals(page)

            login_error = await _detect_login_error(page)
            if login_error:
                if await _save_login_debug(page, username):
                    login_debug_saved = True
                await context.storage_state(path=str(state_file))
                await context.close()
                await browser.close()
                return FirstLoginResult(
                    ok=False,
                    error=login_error,
                    login_debug_saved=login_debug_saved,
                    page_url=page.url,
                )

            if await _detect_2fa_required(page) and not (totp_seed or "").strip():
                if await _save_login_debug(page, username):
                    login_debug_saved = True
                await context.storage_state(path=str(state_file))
                await context.close()
                await browser.close()
                return FirstLoginResult(
                    ok=False,
                    error="Требуется 2FA — укажите TOTP seed в настройках аккаунта",
                    login_debug_saved=login_debug_saved,
                    page_url=page.url,
                )

            if await _detect_challenge(page):
                logger.warning("playwright.challenge_detected", username=username)
                if await _try_resolve_email_challenge(
                    page,
                    email=email,
                    email_password=email_password,
                    imap_host=imap_host,
                ):
                    logger.info("playwright.email_challenge_resolved", username=username)
                else:
                    if await _save_login_debug(page, username):
                        login_debug_saved = True
                    await context.storage_state(path=str(state_file))
                    await context.close()
                    await browser.close()
                    return FirstLoginResult(
                        ok=False,
                        challenge=True,
                        error="challenge required",
                        login_debug_saved=login_debug_saved,
                        page_url=page.url,
                    )

        await _human_wait(1.0, 2.0)
        await _dismiss_post_login_modals(page)
        await _human_scroll(page, total_scrolls=random.randint(2, 4))

        session_id, cookie_names, challenged = await _resolve_instagram_sessionid(
            context, page, state_file
        )
        if not session_id:
            if await _save_login_debug(page, username):
                login_debug_saved = True
            logger.error(
                "playwright.sessionid_missing",
                username=username,
                cookie_names=list(cookie_names),
                page_url=page.url,
            )
            failure_page_url = page.url
            # Detect challenge / login errors on the live page before closing.
            challenged = challenged or await _detect_challenge(page)
            login_error = None if challenged else await _detect_login_error(page)
            still_on_login = False if challenged else await _is_still_on_login_page(page)
            await context.storage_state(path=str(state_file))
            await context.close()
            await browser.close()
            if challenged:
                if await _try_resolve_email_challenge(
                    page,
                    email=email,
                    email_password=email_password,
                    imap_host=imap_host,
                ):
                    session_id, cookie_names, challenged = await _resolve_instagram_sessionid(
                        context, page, state_file
                    )
                    if session_id:
                        await context.storage_state(path=str(state_file))
                        await context.close()
                        await browser.close()
                        return FirstLoginResult(
                            ok=True, session_id=session_id, cookie_names=cookie_names
                        )
                return FirstLoginResult(
                    ok=False,
                    challenge=True,
                    error="challenge required",
                    cookie_names=cookie_names,
                    login_debug_saved=login_debug_saved,
                    page_url=failure_page_url,
                )
            if login_error:
                return FirstLoginResult(
                    ok=False,
                    error=login_error,
                    cookie_names=cookie_names,
                    login_debug_saved=login_debug_saved,
                    page_url=failure_page_url,
                )
            if still_on_login:
                err = (
                    "Браузер остался на странице логина — Instagram не принял учётные данные "
                    "или блокирует автоматический вход"
                )
            elif _is_guest_browse_url(failure_page_url) and (
                "sessionid" not in cookie_names and "ds_user_id" not in cookie_names
            ):
                err = _guest_explore_error_message()
            elif cookie_names:
                preview = ", ".join(cookie_names[:10])
                suffix = f" (+{len(cookie_names) - 10})" if len(cookie_names) > 10 else ""
                err = (
                    f"Instagram не выдал sessionid (cookies: {preview}{suffix}). "
                    "Проверьте пароль, 2FA или challenge"
                )
            else:
                err = "Instagram не выдал sessionid — проверьте пароль, 2FA или challenge"
            return FirstLoginResult(
                ok=False,
                error=err,
                cookie_names=cookie_names,
                login_debug_saved=login_debug_saved,
                page_url=failure_page_url,
            )

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
    login_identifier: Optional[str] = None,
    surface: LoginSurface = "mobile",
    email: Optional[str] = None,
    email_password: Optional[str] = None,
    imap_host: Optional[str] = None,
) -> FirstLoginResult:
    """Synchronous wrapper around the async stealth login.

    If ``fingerprint`` (a :class:`~app.accounts.device_factory.DeviceFingerprint`)
    is supplied, browser context parameters are derived from it for
    consistency with the API path when ``surface`` is ``mobile``.
    """
    proxy_url = (proxy_url or "").strip()
    if not proxy_url:
        logger.error("playwright.proxy_required", username=username)
        return FirstLoginResult(ok=False, error="proxy required")

    device_settings = None
    fp_locale = None
    if fingerprint is not None:
        try:
            fp_locale = fingerprint.locale
        except AttributeError:
            fp_locale = None

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
                headless=headless,
                totp_seed=totp_seed,
                login_identifier=login_identifier,
                surface=surface,
                fingerprint=fingerprint,
                email=email,
                email_password=email_password,
                imap_host=imap_host,
            )
        )
    except Exception as exc:  # noqa: BLE001 - surface Playwright failures to caller
        logger.error("playwright.first_login_failed", username=username, error=str(exc))
        return FirstLoginResult(ok=False, error=str(exc))
