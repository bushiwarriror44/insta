"""Tests for Playwright storage state → sessionid bridge."""
import json

from app.accounts.playwright_session import (
    cookie_names_from_playwright_state,
    import_playwright_session_to_account,
    sessionid_from_playwright_state,
    sessionid_from_playwright_state_data,
)


def test_sessionid_from_playwright_state_reads_cookie(app_env, db_session, make_account):
    make_account(username="pwuser")
    state_dir = app_env.tmp_path / "playwright" / "pwuser"
    state_dir.mkdir(parents=True)
    state_file = state_dir / "state.json"
    state_file.write_text(
        json.dumps(
            {
                "cookies": [
                    {"name": "sessionid", "value": "a" * 40, "domain": ".instagram.com"},
                    {"name": "csrftoken", "value": "x", "domain": ".instagram.com"},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert sessionid_from_playwright_state("pwuser") == "a" * 40


def test_sessionid_from_playwright_state_missing_file(app_env):
    assert sessionid_from_playwright_state("nobody") is None


def test_sessionid_rejects_short_value(app_env):
    data = {"cookies": [{"name": "sessionid", "value": "short"}]}
    assert sessionid_from_playwright_state_data(data) is None


def test_cookie_names_from_playwright_state(app_env):
    state_dir = app_env.tmp_path / "playwright" / "namesuser"
    state_dir.mkdir(parents=True)
    (state_dir / "state.json").write_text(
        json.dumps(
            {
                "cookies": [
                    {"name": "csrftoken", "value": "x"},
                    {"name": "ig_did", "value": "y"},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert cookie_names_from_playwright_state("namesuser") == ["csrftoken", "ig_did"]


def test_import_playwright_session_to_account(db_session, make_account, app_env):
    account = make_account(username="importpw")
    state_dir = app_env.tmp_path / "playwright" / "importpw"
    state_dir.mkdir(parents=True)
    (state_dir / "state.json").write_text(
        json.dumps({"cookies": [{"name": "sessionid", "value": "b" * 40}]}),
        encoding="utf-8",
    )
    assert import_playwright_session_to_account(db_session, account) is True
    db_session.refresh(account)
    assert account.session_id == "b" * 40


def test_import_playwright_session_with_explicit_session_id(db_session, make_account):
    account = make_account(username="directsid")
    sid = "c" * 40
    assert import_playwright_session_to_account(db_session, account, session_id=sid) is True
    db_session.refresh(account)
    assert account.session_id == sid
