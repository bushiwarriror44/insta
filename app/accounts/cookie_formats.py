"""Convert cookies between Dolphin JSON, Playwright state, and instagrapi session formats."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.accounts.playwright_session import playwright_state_path, save_playwright_state
from app.accounts.session_export import export_sessionid
from app.accounts.session_manager import clear_session_file, session_path

CookieExportSource = Literal["playwright", "session_file", "database"]
CookieImportFormat = Literal["dolphin", "playwright_state"]
ImportFormatDetect = Literal["dolphin", "playwright_state", "unknown"]

INSTAGRAM_DOMAIN = ".instagram.com"
MIN_SESSIONID_LEN = 31


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


def sessionid_from_cookies_array(cookies: list) -> str | None:
    for item in cookies:
        if not isinstance(item, dict):
            continue
        if item.get("name") == "sessionid":
            value = item.get("value")
            if isinstance(value, str) and len(value.strip()) >= MIN_SESSIONID_LEN:
                return value.strip()
    return None


def normalize_dolphin_cookie(item: dict) -> dict:
    name = item.get("name")
    value = item.get("value")
    if not isinstance(name, str) or not isinstance(value, str):
        raise CookieFormatError("Каждая cookie должна содержать name и value")
    domain = item.get("domain")
    if not isinstance(domain, str) or not domain.strip():
        domain = INSTAGRAM_DOMAIN
    path = item.get("path")
    if not isinstance(path, str) or not path.strip():
        path = "/"
    out: dict = {
        "name": name,
        "value": value,
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


def cookies_array_to_playwright_state(cookies: list) -> dict:
    normalized = [normalize_dolphin_cookie(c) for c in cookies if isinstance(c, dict)]
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


def _load_playwright_cookies(username: str) -> list[dict] | None:
    path = playwright_state_path(username)
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
) -> tuple[list[dict], CookieExportSource]:
    """Return Dolphin-compatible cookie array and the source used."""
    pw = _load_playwright_cookies(username)
    if pw:
        return pw, "playwright"

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


def import_cookies_data(username: str, data: object) -> CookiesImportResult:
    """Parse imported JSON, persist Playwright state, return sessionid."""
    fmt = detect_import_format(data)
    if fmt == "unknown":
        raise CookieFormatError(
            "Неподдерживаемый формат — ожидается JSON-массив cookies Dolphin "
            "или объект Playwright state.json"
        )

    if fmt == "dolphin":
        assert isinstance(data, list)
        state = cookies_array_to_playwright_state(data)
    else:
        assert isinstance(data, dict)
        cookies = data.get("cookies")
        if not isinstance(cookies, list) or not cookies:
            raise CookieFormatError("Playwright state не содержит cookies")
        state = cookies_array_to_playwright_state(cookies)

    session_id = sessionid_from_cookies_array(state["cookies"])
    if not session_id:
        raise CookieFormatError("В файле не найдена cookie sessionid (31+ символов)")

    save_playwright_state(username, state)
    cleared = clear_session_file(username)
    return CookiesImportResult(
        format=fmt,
        session_id=session_id,
        playwright_state_saved=True,
        session_file_cleared=cleared,
    )


def write_dolphin_cookies_export(username: str, *, db_session_id: str | None = None) -> Path:
    """Write Dolphin cookies JSON to a temp path for FileResponse."""
    cookies, _ = export_dolphin_cookies(username, db_session_id=db_session_id)
    out_dir = playwright_state_path(username).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"cookies_export_{username}.json"
    out_path.write_text(json.dumps(cookies, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path
