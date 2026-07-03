"""Tests for session export helper."""
from __future__ import annotations

import json

from app.accounts.session_export import export_sessionid
from app.accounts.session_manager import session_path


def test_export_prefers_database_session_id(app_env):
    sid = "d" * 40
    result = export_sessionid("alice", db_session_id=sid)
    assert result is not None
    assert result.session_id == sid
    assert result.source == "database"


def test_export_reads_sessionid_from_session_file(app_env):
    path = session_path("bob")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"cookies": {"sessionid": "f" * 40}}),
        encoding="utf-8",
    )
    result = export_sessionid("bob", db_session_id=None)
    assert result is not None
    assert result.session_id == "f" * 40
    assert result.source == "session_file"
    assert result.session_file_exists is True


def test_export_returns_none_when_missing(app_env):
    assert export_sessionid("nobody", db_session_id=None) is None
