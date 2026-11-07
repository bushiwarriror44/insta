"""Persistent Playwright desktop browser profile (Studio + Instagram web)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from app.accounts.device_factory import primary_locale_for_country
from app.accounts.playwright_session import playwright_state_write_path
from app.behavior.playwright_surface import accept_language_header
from app.behavior.warmup_playwright import _CHROME_MAJORS
from app.config import settings

DesktopProfilePlatform = Literal["instagram", "youtube", "tiktok"]

_STUDIO_PROFILE_NAME = "studio_desktop_profile.json"
_INSTAGRAM_WEB_PROFILE_NAME = "web_desktop_profile.json"


@dataclass(frozen=True)
class StudioDesktopProfile:
    user_agent: str
    locale: str
    viewport_width: int
    viewport_height: int
    chrome_major: str
    proxy_country: str | None = None


DesktopPlaywrightProfile = StudioDesktopProfile


def pick_playwright_chrome_major() -> str:
    """Resolve a stable Chrome major for new desktop/mobile browser profiles."""
    return _pick_chrome_major()


def desktop_profile_path(username: str, platform: DesktopProfilePlatform) -> Path:
    if platform == "instagram":
        return settings.playwright_dir / username / _INSTAGRAM_WEB_PROFILE_NAME
    return playwright_state_write_path(username, platform).parent / _STUDIO_PROFILE_NAME


def studio_desktop_profile_path(username: str, platform: str) -> Path:
    """Backward-compatible path helper (studio platforms)."""
    if platform == "instagram":
        return desktop_profile_path(username, "instagram")
    return desktop_profile_path(username, platform)  # type: ignore[arg-type]


def _default_viewport(platform: DesktopProfilePlatform) -> tuple[int, int]:
    if platform == "instagram":
        from app.behavior.playwright_surface import _DEFAULT_DESKTOP

        return _DEFAULT_DESKTOP
    return (settings.browser_studio_vnc_width, settings.browser_studio_vnc_height)


def system_chrome_major() -> str | None:
    """Best-effort Chrome/Chromium major from the host (for UA sync)."""
    return _system_chrome_major()


def _any_chrome_channel_enabled() -> bool:
    from app.behavior.playwright_channel import normalize_playwright_channel

    return any(
        normalize_playwright_channel(ch) == "chrome"
        for ch in (
            settings.browser_vnc_channel,
            settings.playwright_studio_channel,
            settings.playwright_instagram_channel,
        )
    )


def _pick_chrome_major() -> str:
    if _any_chrome_channel_enabled():
        detected = _system_chrome_major()
        if detected:
            return detected
    token = _CHROME_MAJORS[0]
    return token.split(".", 1)[0]


def _system_chrome_major() -> str | None:
    for binary in ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser"):
        path = shutil.which(binary)
        if not path:
            continue
        try:
            proc = subprocess.run(
                [path, "--version"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            text = (proc.stdout or proc.stderr or "").strip()
            match = re.search(r"(\d+)\.", text)
            if match:
                return match.group(1)
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def desktop_chrome_user_agent(chrome_major: str) -> str:
    major = (chrome_major or "131").split(".", 1)[0]
    return (
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
    )


def _load_profile(path: Path) -> StudioDesktopProfile | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        return StudioDesktopProfile(
            user_agent=str(raw["user_agent"]),
            locale=str(raw["locale"]).replace("_", "-"),
            viewport_width=int(raw["viewport_width"]),
            viewport_height=int(raw["viewport_height"]),
            chrome_major=str(raw.get("chrome_major", "131")),
            proxy_country=raw.get("proxy_country"),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _save_profile(path: Path, profile: StudioDesktopProfile) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(profile), indent=2, ensure_ascii=False), encoding="utf-8")


def ensure_desktop_playwright_profile(
    username: str,
    platform: DesktopProfilePlatform,
    *,
    proxy_country: str | None,
    viewport: tuple[int, int] | None = None,
) -> StudioDesktopProfile:
    """Load or create a stable desktop Playwright profile for the account."""
    path = desktop_profile_path(username, platform)
    locale = primary_locale_for_country(proxy_country)
    desired_viewport = viewport if viewport is not None else _default_viewport(platform)

    existing = _load_profile(path)
    if existing is not None:
        updates: dict[str, Any] = {}
        if existing.locale != locale:
            updates["locale"] = locale
            updates["proxy_country"] = proxy_country
        if (existing.viewport_width, existing.viewport_height) != desired_viewport:
            updates["viewport_width"] = desired_viewport[0]
            updates["viewport_height"] = desired_viewport[1]
        if _any_chrome_channel_enabled():
            detected = _system_chrome_major()
            if detected and detected != existing.chrome_major:
                updates["chrome_major"] = detected
                updates["user_agent"] = desktop_chrome_user_agent(detected)
        chrome_major = updates.get("chrome_major", existing.chrome_major)
        user_agent = updates.get("user_agent", existing.user_agent)
        if updates:
            merged = StudioDesktopProfile(
                user_agent=str(user_agent),
                locale=updates.get("locale", existing.locale),
                viewport_width=updates.get("viewport_width", existing.viewport_width),
                viewport_height=updates.get("viewport_height", existing.viewport_height),
                chrome_major=str(chrome_major),
                proxy_country=updates.get("proxy_country", existing.proxy_country),
            )
            _save_profile(path, merged)
            return merged
        return existing

    major = _pick_chrome_major()
    profile = StudioDesktopProfile(
        user_agent=desktop_chrome_user_agent(major),
        locale=locale,
        viewport_width=desired_viewport[0],
        viewport_height=desired_viewport[1],
        chrome_major=major,
        proxy_country=proxy_country,
    )
    _save_profile(path, profile)
    return profile


def ensure_studio_desktop_profile(
    username: str,
    platform: str,
    *,
    proxy_country: str | None,
) -> StudioDesktopProfile:
    return ensure_desktop_playwright_profile(
        username, platform, proxy_country=proxy_country  # type: ignore[arg-type]
    )


def desktop_playwright_context_kwargs(
    profile: StudioDesktopProfile,
    *,
    timezone_id: str,
    storage_state_path: str | None = None,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "locale": profile.locale,
        "timezone_id": timezone_id,
        "user_agent": profile.user_agent,
        "viewport": {"width": profile.viewport_width, "height": profile.viewport_height},
        "device_scale_factor": 1,
        "has_touch": False,
        "is_mobile": False,
        "color_scheme": "light",
        "extra_http_headers": {
            "Accept-Language": accept_language_header(profile.locale),
        },
    }
    if storage_state_path:
        context["storage_state"] = storage_state_path
    return context


def studio_playwright_context_kwargs(
    profile: StudioDesktopProfile,
    *,
    timezone_id: str,
    storage_state_path: str | None = None,
) -> dict[str, Any]:
    return desktop_playwright_context_kwargs(
        profile, timezone_id=timezone_id, storage_state_path=storage_state_path
    )
