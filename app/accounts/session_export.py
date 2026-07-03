"""Read sessionid cookie for admin export (database or instagrapi session file)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, Optional

from app.accounts.session_manager import session_path

SessionSource = Literal["database", "session_file"]


@dataclass(frozen=True)
class ExportedSession:
    session_id: str
    source: SessionSource
    session_file_exists: bool


def _sessionid_from_file(username: str) -> Optional[str]:
    path = session_path(username)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    cookies = data.get("cookies")
    if isinstance(cookies, dict):
        value = cookies.get("sessionid")
        if isinstance(value, str) and value.strip():
            return value.strip()
    auth = data.get("authorization_data")
    if isinstance(auth, dict):
        value = auth.get("sessionid")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def export_sessionid(
    username: str,
    *,
    db_session_id: Optional[str] = None,
) -> Optional[ExportedSession]:
    """Return sessionid for copy/export, preferring the database value."""
    path = session_path(username)
    file_exists = path.exists()

    stored = (db_session_id or "").strip()
    if stored:
        return ExportedSession(
            session_id=stored,
            source="database",
            session_file_exists=file_exists,
        )

    from_file = _sessionid_from_file(username)
    if from_file:
        return ExportedSession(
            session_id=from_file,
            source="session_file",
            session_file_exists=True,
        )

    if file_exists:
        return None
    return None
