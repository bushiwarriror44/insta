"""Shared helpers for Instagram sessionid cookie extraction."""
from __future__ import annotations

MIN_SESSIONID_LEN = 31


def sessionid_from_cookies_array(cookies: list) -> str | None:
    """Return Instagram sessionid from a Playwright/Dolphin cookies array."""
    for item in cookies:
        if not isinstance(item, dict):
            continue
        if item.get("name") == "sessionid":
            value = item.get("value")
            if isinstance(value, str) and len(value.strip()) >= MIN_SESSIONID_LEN:
                return value.strip()
    return None
