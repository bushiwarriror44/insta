"""Tests for cookie format conversion and import/export."""
from __future__ import annotations

import json

import pytest

from app.accounts.cookie_formats import (
    CookieFormatError,
    cookies_array_to_playwright_state,
    detect_import_format,
    export_dolphin_cookies,
    filter_instagram_cookies,
    import_cookies_data,
    instagrapi_session_to_dolphin_cookies,
    sessionid_from_cookies_array,
)
from app.accounts.playwright_session import playwright_state_path
from app.accounts.session_cookie import normalize_sessionid
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


def test_normalize_sessionid_decodes_percent_3a():
    raw = "38945170646%3AG5p9NNhoGGVDGE%3A20%3AAYhWdcBsbiU0mVgtsM9jvb0aRWnNqazSIs__yXPUMw"
    out = normalize_sessionid(raw)
    assert out is not None
    assert "%3A" not in out
    assert out.count(":") == 3
    assert out.startswith("38945170646:")


def test_normalize_sessionid_rejects_short():
    assert normalize_sessionid("short") is None
    assert normalize_sessionid(None) is None


def test_sessionid_from_cookies_array():
    cookies = [
        {"name": "csrftoken", "value": "x"},
        {"name": "sessionid", "value": "b" * 40},
    ]
    assert sessionid_from_cookies_array(cookies) == "b" * 40


def test_sessionid_from_cookies_array_prefers_instagram_domain():
    stale = "s" * 40
    fresh = "f" * 40
    cookies = [
        {"name": "sessionid", "value": stale, "domain": ".facebook.com", "expires": 9999999999},
        {"name": "sessionid", "value": fresh, "domain": ".instagram.com", "expires": 100},
    ]
    assert sessionid_from_cookies_array(cookies) == fresh


def test_sessionid_from_cookies_array_prefers_later_expires():
    older = "o" * 40
    newer = "n" * 40
    cookies = [
        {"name": "sessionid", "value": older, "domain": ".instagram.com", "expires": 1000},
        {"name": "sessionid", "value": newer, "domain": ".instagram.com", "expires": 9000},
    ]
    assert sessionid_from_cookies_array(cookies) == newer


def test_sessionid_from_cookies_array_decodes_url():
    cookies = [
        {
            "name": "sessionid",
            "value": "38945170646%3AG5p9NNhoGGVDGE%3A20%3AAYhWdcBsbiU0mVgtsM9jvb0aRWnNqazSIs__yXPUMw",
            "domain": ".instagram.com",
        }
    ]
    sid = sessionid_from_cookies_array(cookies)
    assert sid is not None
    assert ":" in sid
    assert "%3A" not in sid


def test_filter_instagram_cookies_drops_noise():
    cookies = [
        {"name": "AEC", "value": "x", "domain": ".google.com"},
        {"name": "sessionid", "value": "s" * 40, "domain": ".instagram.com"},
        {"name": "mid", "value": "m", "domain": ".instagram.com"},
    ]
    filtered = filter_instagram_cookies(cookies)
    assert len(filtered) == 2
    assert all("instagram.com" in c["domain"] for c in filtered)


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
    assert result.session_file_cleared is False
    assert playwright_state_path("dolphinuser").exists()


def test_import_cookies_preserves_mobile_session_file(app_env):
    from app.accounts.session_manager import session_path

    sid = "p" * 40
    path = session_path("keepmobile")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"mobile": true}', encoding="utf-8")
    data = [{"name": "sessionid", "value": sid, "domain": ".instagram.com"}]
    result = import_cookies_data("keepmobile", data)
    assert result.session_file_cleared is False
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["mobile"] is True


def test_import_cookies_data_decodes_and_filters_noise(app_env):
    encoded = "38945170646%3AG5p9NNhoGGVDGE%3A20%3AAYhWdcBsbiU0mVgtsM9jvb0aRWnNqazSIs__yXPUMw"
    data = [
        {"name": "AEC", "value": "noise", "domain": ".google.com"},
        {"name": "sessionid", "value": encoded, "domain": ".instagram.com"},
        {"name": "csrftoken", "value": "tok", "domain": ".instagram.com"},
    ]
    result = import_cookies_data("decodeuser", data)
    assert "%3A" not in result.session_id
    assert result.session_id.startswith("38945170646:")
    state = json.loads(playwright_state_path("decodeuser").read_text(encoding="utf-8"))
    domains = {c["domain"] for c in state["cookies"]}
    assert ".google.com" not in domains
    sid_cookie = next(c for c in state["cookies"] if c["name"] == "sessionid")
    assert sid_cookie["value"] == result.session_id


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
