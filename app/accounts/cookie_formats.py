"""Convert cookies between Dolphin JSON, Playwright state, and instagrapi session formats."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.accounts.playwright_session import (
    playwright_state_path,
    playwright_state_write_path,
    save_playwright_state,
)
from app.accounts.session_cookie import (
    normalize_sessionid,
    sessionid_from_cookies_array,
)
from app.accounts.session_export import export_sessionid
from app.accounts.session_manager import session_path

CookieExportSource = Literal["playwright", "session_file", "database"]
CookieImportFormat = Literal["dolphin", "playwright_state"]
ImportFormatDetect = Literal["dolphin", "playwright_state", "unknown"]

INSTAGRAM_DOMAIN = ".instagram.com"
YOUTUBE_DOMAIN = ".youtube.com"
TIKTOK_DOMAIN = ".tiktok.com"

_PLATFORM_NEEDLES: dict[str, tuple[str, ...]] = {
    "instagram": ("instagram.com",),
    "youtube": ("youtube.com", "google.com", "youtu.be", "gstatic.com"),
    "tiktok": ("tiktok.com",),
}
_PLATFORM_DEFAULT_DOMAIN = {
    "instagram": INSTAGRAM_DOMAIN,
    "youtube": YOUTUBE_DOMAIN,
    "tiktok": TIKTOK_DOMAIN,
}
STUDIO_PLATFORMS = frozenset({"youtube", "tiktok"})


class CookieFormatError(ValueError):
    """Raised when cookie data cannot be parsed or is missing sessionid."""


@dataclass(frozen=True)
class CookiesImportResult:
    format: CookieImportFormat
    session_id: str
    playwright_state_saved: bool
    session_file_cleared: bool


def detect_import_format(data: object) -> ImportFormatDetect:
    if isinstance(data, list) and data:
        if all(
            isinstance(item, dict) and "name" in item and "value" in item
            for item in data
        ):
            return "dolphin"
        return "unknown"
    if isinstance(data, dict):
        cookies = data.get("cookies")
        if isinstance(cookies, list):
            return "playwright_state"
    return "unknown"


def _is_instagram_cookie_domain(domain: str | None) -> bool:
    if not isinstance(domain, str) or not domain.strip():
        return True
    return "instagram.com" in domain.lower()


def _domain_matches(domain: str | None, needles: tuple[str, ...]) -> bool:
    if not isinstance(domain, str) or not domain.strip():
        return True
    lowered = domain.lower()
    return any(needle in lowered for needle in needles)


def normalize_dolphin_cookie(item: dict, *, default_domain: str = INSTAGRAM_DOMAIN) -> dict:
    name = item.get("name")
    value = item.get("value")
    if not isinstance(name, str) or not isinstance(value, str):
        raise CookieFormatError("Каждая cookie должна содержать name и value")
    domain = item.get("domain")
    if not isinstance(domain, str) or not domain.strip():
        domain = default_domain
    path = item.get("path")
    if not isinstance(path, str) or not path.strip():
        path = "/"
    cookie_value = value
    if name == "sessionid":
        decoded = normalize_sessionid(value)
        if decoded is not None:
            cookie_value = decoded
    out: dict = {
        "name": name,
        "value": cookie_value,
        "domain": domain,
        "path": path,
        "secure": bool(item.get("secure", True)),
        "httpOnly": bool(item.get("httpOnly", item.get("httponly", False))),
    }
    same_site = item.get("sameSite", item.get("samesite"))
    if isinstance(same_site, str) and same_site:
        out["sameSite"] = same_site
    expires = item.get("expires", item.get("expirationDate"))
    if expires is not None:
        out["expires"] = expires
    return out


def filter_instagram_cookies(cookies: list) -> list:
    """Keep only Instagram-domain cookies (drop Google/ads noise from Dolphin dumps)."""
    return filter_cookies_for_platform(cookies, "instagram")


def filter_cookies_for_platform(cookies: list, platform: str = "instagram") -> list:
    needles = _PLATFORM_NEEDLES.get(platform, _PLATFORM_NEEDLES["instagram"])
    kept = [
        c
        for c in cookies
        if isinstance(c, dict) and _domain_matches(c.get("domain"), needles)
    ]
    return kept if kept else [c for c in cookies if isinstance(c, dict)]


def cookies_match_platform(cookies: list, platform: str) -> bool:
    """True when the jar has cookies for *platform* (IG also needs sessionid)."""
    needles = _PLATFORM_NEEDLES.get(platform, _PLATFORM_NEEDLES["instagram"])
    matched = [
        c
        for c in cookies
        if isinstance(c, dict) and _domain_matches(c.get("domain"), needles)
    ]
    if not matched:
        return False
    if platform == "instagram":
        return sessionid_from_cookies_array(matched) is not None
    return True


def studio_session_ready(username: str, platform: str) -> bool:
    """True when Playwright state.json has YouTube/TikTok cookies (not IG sessionid)."""
    if platform not in STUDIO_PLATFORMS:
        return False
    cookies = _load_playwright_cookies(username, platform)
    if not cookies:
        return False
    return cookies_match_platform(cookies, platform)


def cookies_array_to_playwright_state(cookies: list, platform: str = "instagram") -> dict:
    filtered = filter_cookies_for_platform(cookies, platform)
    default_domain = _PLATFORM_DEFAULT_DOMAIN.get(platform, INSTAGRAM_DOMAIN)
    normalized = [
        normalize_dolphin_cookie(c, default_domain=default_domain)
        for c in filtered
        if isinstance(c, dict)
    ]
    if not normalized:
        raise CookieFormatError("Список cookies пуст")
    return {"cookies": normalized, "origins": []}


def instagrapi_session_to_dolphin_cookies(session_data: dict) -> list[dict]:
    cookies = session_data.get("cookies")
    if not isinstance(cookies, dict) or not cookies:
        return []
    out: list[dict] = []
    for name, value in cookies.items():
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        out.append(
            normalize_dolphin_cookie(
                {"name": name, "value": value, "domain": INSTAGRAM_DOMAIN}
            )
        )
    return out


def _load_playwright_cookies(username: str, platform: str | None = None) -> list[dict] | None:
    path = playwright_state_path(username, platform)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    cookies = data.get("cookies")
    if not isinstance(cookies, list) or not cookies:
        return None
    return [normalize_dolphin_cookie(c) for c in cookies if isinstance(c, dict)]


def _load_instagrapi_cookies(username: str) -> list[dict] | None:
    path = session_path(username)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    cookies = instagrapi_session_to_dolphin_cookies(data)
    return cookies or None


def export_dolphin_cookies(
    username: str,
    *,
    db_session_id: str | None = None,
    platform: str = "instagram",
) -> tuple[list[dict], CookieExportSource]:
    """Return Dolphin-compatible cookie array and the source used."""
    kind = platform or "instagram"
    pw = _load_playwright_cookies(username, kind if kind in STUDIO_PLATFORMS else None)
    if pw:
        filtered = [
            c
            for c in pw
            if isinstance(c, dict)
            and _domain_matches(c.get("domain"), _PLATFORM_NEEDLES.get(kind, _PLATFORM_NEEDLES["instagram"]))
        ]
        if filtered:
            return filtered, "playwright"
        if kind in STUDIO_PLATFORMS:
            raise CookieFormatError(
                "Playwright state не содержит cookies этой площадки — "
                "импортируйте cookies или сохраните сессию в браузере"
            )

    if kind in STUDIO_PLATFORMS:
        raise CookieFormatError(
            "Playwright state не найден — импортируйте cookies или сохраните сессию в браузере"
        )

    ig = _load_instagrapi_cookies(username)
    if ig:
        return ig, "session_file"

    exported = export_sessionid(username, db_session_id=db_session_id)
    if exported is None:
        raise CookieFormatError("Сессия не найдена — импортируйте cookies или войдите в аккаунт")

    return (
        [
            normalize_dolphin_cookie(
                {
                    "name": "sessionid",
                    "value": exported.session_id,
                    "domain": INSTAGRAM_DOMAIN,
                    "httpOnly": True,
                    "secure": True,
                }
            )
        ],
        "database",
    )


def import_cookies_data(
    username: str, data: object, *, platform: str = "instagram"
) -> CookiesImportResult:
    """Parse imported JSON, persist Playwright state, return sessionid when present."""
    fmt = detect_import_format(data)
    if fmt == "unknown":
        raise CookieFormatError(
            "Неподдерживаемый формат — ожидается JSON-массив cookies Dolphin "
            "или объект Playwright state.json"
        )

    if fmt == "dolphin":
        assert isinstance(data, list)
        state = cookies_array_to_playwright_state(data, platform=platform)
    else:
        assert isinstance(data, dict)
        cookies = data.get("cookies")
        if not isinstance(cookies, list) or not cookies:
            raise CookieFormatError("Playwright state не содержит cookies")
        state = cookies_array_to_playwright_state(cookies, platform=platform)

    session_id = sessionid_from_cookies_array(state["cookies"]) or ""
    if platform == "instagram" and not session_id:
        raise CookieFormatError("В файле не найдена cookie sessionid (31+ символов)")
    if session_id:
        for cookie in state["cookies"]:
            if isinstance(cookie, dict) and cookie.get("name") == "sessionid":
                cookie["value"] = session_id

    save_playwright_state(username, state, platform)
    # Keep mobile session_*.json if present — web cookies live in Playwright state;
    # clearing the dump would break publish/probe that still use the mobile file.
    return CookiesImportResult(
        format=fmt,
        session_id=session_id,
        playwright_state_saved=True,
        session_file_cleared=False,
    )


def write_dolphin_cookies_export(
    username: str,
    *,
    db_session_id: str | None = None,
    as_txt: bool = False,
    platform: str = "instagram",
) -> Path:
    """Write Dolphin cookies JSON to a temp path for FileResponse."""
    cookies, _ = export_dolphin_cookies(
        username, db_session_id=db_session_id, platform=platform
    )
    out_dir = playwright_state_write_path(username, platform).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".txt" if as_txt else ".json"
    out_path = out_dir / f"cookies_export_{username}{suffix}"
    out_path.write_text(json.dumps(cookies, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path
