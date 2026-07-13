"""Playwright browser surface profiles: mobile vs desktop emulation."""
from __future__ import annotations

from typing import Any, Literal, Optional

LoginSurface = Literal["mobile", "desktop"]

_DEFAULT_SURFACE: LoginSurface = "mobile"


def resolve_playwright_surface(value: str | None) -> LoginSurface:
    """Normalize user/account value to a supported login surface."""
    normalized = (value or "").strip().lower()
    if normalized in ("desktop", "web", "pc"):
        return "desktop"
    return _DEFAULT_SURFACE


def stealth_init_script(surface: LoginSurface) -> str:
    touch_points = 5 if surface == "mobile" else 0
    return f"""
() => {{
  Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});
  Object.defineProperty(navigator, 'maxTouchPoints', {{ get: () => {touch_points} }});
  window.chrome = window.chrome || {{ runtime: {{}} }};
  const originalQuery = window.navigator.permissions.query;
  window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
      ? Promise.resolve({{ state: Notification.permission }})
      : originalQuery(parameters)
  );
}}
"""


_LIGHTWEIGHT_CHROMIUM_ARGS = [
    "--disable-gpu",
    "--disable-background-networking",
    "--disable-sync",
    "--disable-translate",
    "--no-first-run",
    "--disable-features=AudioServiceOutOfProcess",
]


def browser_launch_args(surface: LoginSurface, *, lightweight: bool = False) -> list[str]:
    if surface == "mobile":
        window_size = "430,932"
    else:
        window_size = "1280,800"
    args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-infobars",
        f"--window-size={window_size}",
        "--disable-features=IsolateOrigins,site-per-process",
    ]
    if lightweight:
        args.extend(_LIGHTWEIGHT_CHROMIUM_ARGS)
    return args


def vnc_screen_size(surface: LoginSurface, *, lightweight: bool = False) -> str:
    """Xvfb screen geometry for headed sessions."""
    depth = "16" if lightweight else "24"
    if surface == "mobile":
        return f"430x932x{depth}"
    return f"1280x800x{depth}"


def mouse_jitter_bounds(surface: LoginSurface) -> tuple[int, int, int, int]:
    """Return max_x, max_y, min_x, min_y for human mouse jitter."""
    if surface == "mobile":
        return 380, 880, 20, 40
    return 1100, 680, 120, 120


def _accept_language_for_locale(locale: str) -> str:
    normalized = (locale or "en-US").replace("_", "-")
    base = normalized.split("-", 1)[0]
    return f"{normalized},{base};q=0.9"


def _device_settings_from_fingerprint(fingerprint) -> dict | None:
    if fingerprint is None:
        return None
    try:
        settings = fingerprint.settings
        if isinstance(settings, dict):
            nested = settings.get("device_settings")
            if isinstance(nested, dict):
                return nested
            return settings
    except AttributeError:
        return None
    return None


def playwright_context_kwargs(
    surface: LoginSurface,
    *,
    fingerprint=None,
    locale: str = "en-US",
    timezone_id: str = "UTC",
    storage_state_path: str | None = None,
    lightweight: bool = False,
) -> dict[str, Any]:
    """Build Playwright ``browser.new_context`` kwargs for the given surface."""
    from app.behavior.warmup_playwright import (
        _desktop_ua,
        _desktop_viewport,
        _ua_for_device,
        _viewport_from_resolution,
    )

    fp_locale = getattr(fingerprint, "locale", None) if fingerprint is not None else None
    resolved_locale = (locale or fp_locale or "en-US").replace("_", "-")
    device_settings = _device_settings_from_fingerprint(fingerprint)

    if surface == "mobile":
        resolution = None
        if device_settings:
            resolution = device_settings.get("resolution")
        user_agent = _ua_for_device(device_settings, None)
        viewport = _viewport_from_resolution(resolution)
        mobile_scale = 2 if lightweight else 3
        context: dict[str, Any] = {
            "locale": resolved_locale,
            "timezone_id": timezone_id,
            "user_agent": user_agent,
            "viewport": viewport,
            "device_scale_factor": mobile_scale,
            "has_touch": True,
            "is_mobile": True,
            "color_scheme": "light",
            "extra_http_headers": {
                "Accept-Language": _accept_language_for_locale(resolved_locale),
            },
        }
    else:
        context = {
            "locale": resolved_locale,
            "timezone_id": timezone_id,
            "user_agent": _desktop_ua(),
            "viewport": _desktop_viewport(),
            "device_scale_factor": 1,
            "has_touch": False,
            "is_mobile": False,
            "color_scheme": "light",
            "extra_http_headers": {
                "Accept-Language": _accept_language_for_locale(resolved_locale),
            },
        }

    if storage_state_path:
        context["storage_state"] = storage_state_path
    return context


def surface_label(surface: LoginSurface) -> str:
    return "mobile" if surface == "mobile" else "desktop"
