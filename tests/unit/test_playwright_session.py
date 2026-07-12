"""Tests for Playwright storage state → sessionid bridge."""
import json

from app.accounts.playwright_session import (
    import_playwright_session_to_account,
    sessionid_from_playwright_state,
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
