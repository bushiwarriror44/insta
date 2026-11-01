"""Tests for batch Studio login helpers."""
from __future__ import annotations

from app.accounts.studio_login_service import list_studio_accounts, run_studio_login_batch
from app.db import Platform


def test_list_studio_accounts_imported_only(db_session, make_account, make_proxy):
    mobile = make_proxy(label="am-mobile-01")
    other = make_proxy(label="legacy-1")
    yt_ok = make_account(username="yt1", platform=Platform.youtube, proxy=mobile)
    make_account(username="yt2", platform=Platform.youtube, proxy=other)
    listed = list_studio_accounts(db_session, imported_only=True)
    assert [a.username for a in listed] == [yt_ok.username]


def test_run_studio_login_batch_skips_no_password(db_session, make_account, make_proxy):
    proxy = make_proxy(label="am-mobile-02")
    account = make_account(username="nopw", platform=Platform.youtube, proxy=proxy, password="")
    rows = run_studio_login_batch(db_session, [account], force=False)
    assert rows[0]["ok"] is False
    assert "пароль" in (rows[0]["error"] or "").lower()
