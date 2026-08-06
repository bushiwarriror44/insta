"""Tests for mint_mobile_session service."""
from __future__ import annotations

from app.accounts.mint_mobile_session import mint_mobile_session
from app.db import AccountStatus


def test_mint_mobile_session_updates_db(db_session, make_account, make_proxy, monkeypatch):
    proxy = make_proxy(label="mint-px", country="PL")
    account = make_account(
        username="mintuser",
        password="secret",
        proxy=proxy,
    )
    account.login_identifier = "user@example.com"
    db_session.commit()
    sid = "m" * 40

    monkeypatch.setattr(
        "app.accounts.mint_mobile_session.ensure_fingerprint_and_proxy",
        lambda *a, **k: object(),
    )
    monkeypatch.setattr(
        "app.accounts.mint_mobile_session.make_handler",
        lambda *a, **k: (lambda u, c: "123456"),
    )
    monkeypatch.setattr(
        "app.accounts.mint_mobile_session.login_and_export_sessionid",
        lambda *a, **k: sid,
    )
    monkeypatch.setattr(
        "app.accounts.mint_mobile_session.log_account_credentials",
        lambda *a, **k: None,
    )

    out = mint_mobile_session(account, db_session)
    assert out.ok is True
    assert out.session_id == sid
    db_session.refresh(account)
    assert account.session_id == sid
    assert account.status == AccountStatus.active


def test_mint_mobile_session_requires_password(db_session, make_account, make_proxy, monkeypatch):
    proxy = make_proxy(label="mint-nopw")
    account = make_account(username="nopw", password="", proxy=proxy)
    monkeypatch.setattr(
        "app.accounts.mint_mobile_session.log_account_credentials",
        lambda *a, **k: None,
    )
    out = mint_mobile_session(account, db_session)
    assert out.ok is False
    assert "пароль" in (out.error or "").lower()
