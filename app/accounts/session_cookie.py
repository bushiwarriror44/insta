"""Shared helpers for Instagram sessionid cookie extraction."""
from __future__ import annotations

from urllib.parse import unquote

MIN_SESSIONID_LEN = 31


def normalize_sessionid(value: str | None) -> str | None:
    """Strip and URL-decode sessionid (Dolphin often exports ``%3A`` instead of ``:``)."""
    if value is None:
        return None
    cleaned = unquote(value.strip())
    if len(cleaned) < MIN_SESSIONID_LEN:
        return None
    return cleaned


def sessionid_from_cookies_array(cookies: list) -> str | None:
    """Return Instagram sessionid from a Playwright/Dolphin cookies array."""
    for item in cookies:
        if not isinstance(item, dict):
            continue
        if item.get("name") == "sessionid":
            return normalize_sessionid(item.get("value") if isinstance(item.get("value"), str) else None)
    return None
