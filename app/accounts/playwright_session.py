"""Bridge Playwright storage state to account.session_id."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.accounts.session_cookie import sessionid_from_cookies_array
from app.config import settings
from app.db import Account


def playwright_state_path(username: str) -> Path:
    return settings.playwright_dir / username / "state.json"


def login_debug_screenshot_path(username: str) -> Path:
    return settings.playwright_dir / username / "login_debug.png"


def storage_state_has_session(username: str) -> bool:
    """True when Playwright state already contains a valid sessionid."""
    return sessionid_from_playwright_state(username) is not None


def save_playwright_state(username: str, state: dict) -> Path:
    """Persist Playwright storage state JSON for *username*."""
    path = playwright_state_path(username)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _load_playwright_state_data(username: str) -> dict | None:
    path = playwright_state_path(username)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def sessionid_from_playwright_state_data(data: dict) -> str | None:
    """Extract Instagram sessionid from an in-memory Playwright state dict."""
    cookies = data.get("cookies")
    if not isinstance(cookies, list):
        return None
    return sessionid_from_cookies_array(cookies)


def sessionid_from_playwright_state(username: str) -> str | None:
    """Extract Instagram sessionid cookie from Playwright storage state."""
    data = _load_playwright_state_data(username)
    if data is None:
        return None
    return sessionid_from_playwright_state_data(data)


def cookie_names_from_playwright_state(username: str) -> list[str]:
    """Return cookie names from Playwright state (values omitted for diagnostics)."""
    data = _load_playwright_state_data(username)
    if data is None:
        return []
    cookies = data.get("cookies")
    if not isinstance(cookies, list):
        return []
    names: list[str] = []
    for item in cookies:
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str) and name:
                names.append(name)
    return names


def import_playwright_session_to_account(
    db: Session,
    account: Account,
    *,
    session_id: str | None = None,
) -> bool:
    """Persist sessionid into the account row (from arg or Playwright state file).

    Does not clear the mobile ``session_*.json`` dump — web cookies and mobile
    dumps coexist so publish can still resume from the file.
    """
    resolved = (session_id or "").strip() or sessionid_from_playwright_state(account.username)
    if not resolved:
        return False
    account.session_id = resolved
    db.commit()
    db.refresh(account)
    return True
