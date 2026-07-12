"""Tests for first-login API service."""
from datetime import datetime, timezone

from app.accounts.first_login_service import run_account_first_login
from app.api.schemas import (
    AccountConnectionTestOut,
    InstagramAuthStepOut,
    ProxyHealthStepOut,
    SessionStorageStepOut,
)
from app.behavior.warmup_playwright import FirstLoginResult


def _connection_ok(username: str) -> AccountConnectionTestOut:
    now = datetime.now(timezone.utc)
    return AccountConnectionTestOut(
        username=username,
        proxy_assigned=True,
        proxy_label="px",
        proxy_health=ProxyHealthStepOut(ok=True, instagram_reachable=True),
        session_storage=SessionStorageStepOut(
            has_session_id=True,
            session_file_exists=False,
            device_file_exists=True,
            session_source="database",
        ),
        instagram_auth=InstagramAuthStepOut(ok=True, method="sessionid", challenge=False),
        overall_ok=True,
        checked_at=now,
        run_id=99,
        logs=[],
    )


def test_first_login_service_success(db_session, make_account, make_proxy, monkeypatch):
    proxy = make_proxy(label="px-fl")
    account = make_account(username="fluser", proxy=proxy)

    monkeypatch.setattr(
        "app.accounts.first_login_service.playwright_browsers_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.accounts.first_login_service.first_login",
        lambda **kwargs: FirstLoginResult(ok=True, session_id="d" * 40),
    )
    captured: dict = {}

    def _import(db, acc, **kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(
        "app.accounts.first_login_service.import_playwright_session_to_account",
        _import,
    )
    monkeypatch.setattr(
        "app.accounts.first_login_service.run_account_connection_test",
        lambda acc, db: _connection_ok(acc.username),
    )

    out = run_account_first_login(account, db_session)
    assert out.ok is True
    assert out.session_imported is True
    assert out.run_id > 0
    assert captured.get("session_id") == "d" * 40


def test_first_login_service_challenge(db_session, make_account, make_proxy, monkeypatch):
    proxy = make_proxy(label="px-ch")
    account = make_account(username="chuser", proxy=proxy)

    monkeypatch.setattr(
        "app.accounts.first_login_service.playwright_browsers_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.accounts.first_login_service.first_login",
        lambda **kwargs: FirstLoginResult(ok=False, challenge=True),
    )

    out = run_account_first_login(account, db_session)
    assert out.ok is False
    assert out.challenge is True


def test_first_login_service_normalizes_invalid_proxy_timezone(
    db_session, make_account, make_proxy, monkeypatch
):
    proxy = make_proxy(label="px-tz", country="US", timezone="+9 UTC")
    account = make_account(username="tzuser", proxy=proxy)
    captured: dict = {}

    monkeypatch.setattr(
        "app.accounts.first_login_service.playwright_browsers_available",
        lambda: True,
    )

    def _fake_first_login(**kwargs):
        captured.update(kwargs)
        return FirstLoginResult(ok=True, session_id="e" * 40)

    monkeypatch.setattr("app.accounts.first_login_service.first_login", _fake_first_login)
    monkeypatch.setattr(
        "app.accounts.first_login_service.import_playwright_session_to_account",
        lambda db, acc, **kwargs: True,
    )
    monkeypatch.setattr(
        "app.accounts.first_login_service.run_account_connection_test",
        lambda acc, db: _connection_ok(acc.username),
    )

    out = run_account_first_login(account, db_session)
    assert out.ok is True
    assert captured["timezone_id"] == "America/New_York"


def test_first_login_service_api_fallback_after_playwright_fail(
    db_session, make_account, make_proxy, monkeypatch
):
    proxy = make_proxy(label="px-api")
    account = make_account(username="apiuser", proxy=proxy)

    monkeypatch.setattr(
        "app.accounts.first_login_service.playwright_browsers_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.accounts.first_login_service.first_login",
        lambda **kwargs: FirstLoginResult(
            ok=False,
            error="Instagram не выдал sessionid (cookies: csrftoken)",
            cookie_names=("csrftoken",),
        ),
    )
    monkeypatch.setattr(
        "app.accounts.first_login_service.login_and_export_sessionid",
        lambda *args, **kwargs: "f" * 40,
    )
    monkeypatch.setattr(
        "app.accounts.first_login_service.run_account_connection_test",
        lambda acc, db: _connection_ok(acc.username),
    )

    out = run_account_first_login(account, db_session)
    assert out.ok is True
    assert out.session_imported is True
    db_session.refresh(account)
    assert account.session_id == "f" * 40


def test_first_login_service_bad_password_message(
    db_session, make_account, make_proxy, monkeypatch
):
    from app.accounts.session_manager import AuthenticationError

    proxy = make_proxy(label="px-bad")
    account = make_account(username="badpw", proxy=proxy)

    monkeypatch.setattr(
        "app.accounts.first_login_service.playwright_browsers_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.accounts.first_login_service.first_login",
        lambda **kwargs: FirstLoginResult(
            ok=False,
            error="Браузер остался на странице логина",
            login_debug_saved=True,
        ),
    )

    def _raise_bad_password(*args, **kwargs):
        raise AuthenticationError("bad password")

    monkeypatch.setattr(
        "app.accounts.first_login_service.login_and_export_sessionid",
        _raise_bad_password,
    )

    out = run_account_first_login(account, db_session)
    assert out.ok is False
    assert "Неверный пароль" in (out.error or "")
    assert out.login_debug_available is True


def test_first_login_service_no_playwright(db_session, make_account, monkeypatch):
    account = make_account(username="nopw")

    monkeypatch.setattr(
        "app.accounts.first_login_service.playwright_browsers_available",
        lambda: False,
    )

    out = run_account_first_login(account, db_session)
    assert out.ok is False
    assert "install-playwright" in (out.error or "").lower() or "Chromium" in (out.error or "")
