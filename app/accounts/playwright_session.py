"""Bridge Playwright storage state to account.session_id."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.accounts.session_manager import clear_session_file
from app.config import settings
from app.db import Account


def playwright_state_path(username: str) -> Path:
    return settings.playwright_dir / username / "state.json"


def sessionid_from_playwright_state(username: str) -> str | None:
    """Extract Instagram sessionid cookie from Playwright storage state."""
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
    if not isinstance(cookies, list):
        return None
    for item in cookies:
        if not isinstance(item, dict):
            continue
        if item.get("name") == "sessionid":
            value = item.get("value")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def import_playwright_session_to_account(db: Session, account: Account) -> bool:
    """Persist sessionid from Playwright state into the account row."""
    session_id = sessionid_from_playwright_state(account.username)
    if not session_id:
        return False
    account.session_id = session_id
    clear_session_file(account.username)
    db.commit()
    db.refresh(account)
    return True
