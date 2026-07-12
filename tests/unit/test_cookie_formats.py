"""Tests for cookie format conversion and import/export."""
from __future__ import annotations

import json

import pytest

from app.accounts.cookie_formats import (
    CookieFormatError,
    cookies_array_to_playwright_state,
    detect_import_format,
    export_dolphin_cookies,
    import_cookies_data,
    instagrapi_session_to_dolphin_cookies,
    sessionid_from_cookies_array,
)
from app.accounts.playwright_session import playwright_state_path
from app.accounts.session_manager import session_path


def test_detect_import_format_dolphin():
    data = [{"name": "sessionid", "value": "a" * 40}]
    assert detect_import_format(data) == "dolphin"


def test_detect_import_format_playwright():
    data = {"cookies": [{"name": "sessionid", "value": "a" * 40}], "origins": []}
    assert detect_import_format(data) == "playwright_state"


def test_detect_import_format_unknown():
    assert detect_import_format({"foo": "bar"}) == "unknown"
    assert detect_import_format([]) == "unknown"


def test_sessionid_from_cookies_array():
    cookies = [
        {"name": "csrftoken", "value": "x"},
        {"name": "sessionid", "value": "b" * 40},
    ]
    assert sessionid_from_cookies_array(cookies) == "b" * 40


def test_instagrapi_session_to_dolphin_cookies():
    data = {"cookies": {"sessionid": "c" * 40, "csrftoken": "tok"}}
    out = instagrapi_session_to_dolphin_cookies(data)
    assert len(out) == 2
    names = {c["name"] for c in out}
    assert names == {"sessionid", "csrftoken"}


def test_cookies_array_to_playwright_state():
    state = cookies_array_to_playwright_state(
        [{"name": "sessionid", "value": "d" * 40, "domain": ".instagram.com"}]
    )
    assert "cookies" in state
    assert state["origins"] == []
    assert state["cookies"][0]["path"] == "/"


def test_export_dolphin_cookies_prefers_playwright(app_env):
    state_dir = app_env.tmp_path / "playwright" / "alice"
    state_dir.mkdir(parents=True)
    (state_dir / "state.json").write_text(
        json.dumps(
            {
                "cookies": [
                    {"name": "sessionid", "value": "e" * 40, "domain": ".instagram.com"},
                    {"name": "csrftoken", "value": "csrf", "domain": ".instagram.com"},
                ],
                "origins": [],
            }
        ),
        encoding="utf-8",
    )
    cookies, source = export_dolphin_cookies("alice")
    assert source == "playwright"
    assert len(cookies) == 2


def test_export_dolphin_cookies_from_session_file(app_env):
    path = session_path("bob")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"cookies": {"sessionid": "f" * 40, "csrftoken": "x"}}),
        encoding="utf-8",
    )
    cookies, source = export_dolphin_cookies("bob")
    assert source == "session_file"
    assert any(c["name"] == "sessionid" for c in cookies)


def test_export_dolphin_cookies_from_database(app_env):
    cookies, source = export_dolphin_cookies("carol", db_session_id="g" * 40)
    assert source == "database"
    assert len(cookies) == 1
    assert cookies[0]["name"] == "sessionid"


def test_export_dolphin_cookies_missing_raises(app_env):
    with pytest.raises(CookieFormatError):
        export_dolphin_cookies("nobody")


def test_import_cookies_data_dolphin(app_env):
    sid = "h" * 40
    data = [
        {"name": "sessionid", "value": sid, "domain": ".instagram.com"},
        {"name": "csrftoken", "value": "tok"},
    ]
    result = import_cookies_data("dolphinuser", data)
    assert result.format == "dolphin"
    assert result.session_id == sid
    assert playwright_state_path("dolphinuser").exists()


def test_import_cookies_data_playwright_state(app_env):
    sid = "i" * 40
    data = {
        "cookies": [{"name": "sessionid", "value": sid}],
        "origins": [],
    }
    result = import_cookies_data("pwimport", data)
    assert result.format == "playwright_state"
    assert result.session_id == sid


def test_import_cookies_data_missing_sessionid(app_env):
    with pytest.raises(CookieFormatError, match="sessionid"):
        import_cookies_data("bad", [{"name": "csrftoken", "value": "x"}])


def test_import_cookies_data_unknown_format(app_env):
    with pytest.raises(CookieFormatError, match="Неподдерживаемый"):
        import_cookies_data("bad", {"not": "valid"})
