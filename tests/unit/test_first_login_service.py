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


def test_first_login_service_skips_mobile_connection_probe(
    db_session, make_account, make_proxy, monkeypatch
):
    proxy = make_proxy(label="px-noprobe")
    account = make_account(username="noprobe", proxy=proxy)
    called = {"n": 0}

    def _probe(acc, db):
        called["n"] += 1
        return _connection_ok(acc.username)

    monkeypatch.setattr(
        "app.accounts.first_login_service.playwright_browsers_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.accounts.first_login_service.first_login",
        lambda **kwargs: FirstLoginResult(ok=True, session_id="c" * 40),
    )

    def _import(db, acc, **kwargs):
        acc.session_id = kwargs.get("session_id") or "c" * 40
        db.commit()
        return True

    monkeypatch.setattr(
        "app.accounts.first_login_service.import_playwright_session_to_account",
        _import,
    )
    monkeypatch.setattr(
        "app.accounts.connection_test.run_account_connection_test",
        _probe,
    )

    out = run_account_first_login(account, db_session)
    assert out.ok is True
    assert out.connection_test is None
    assert called["n"] == 0
    assert any("mobile api-проверка пропущена" in line.message.lower() for line in out.logs)


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

    out = run_account_first_login(account, db_session)
    assert out.ok is True
    assert out.session_imported is True
    assert out.run_id > 0
    assert captured.get("session_id") == "d" * 40


def test_first_login_service_challenge(db_session, make_account, make_proxy, monkeypatch):
    from app.db.models import Event, EventLevel

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
    events = db_session.query(Event).filter(Event.account_id == account.id).all()
    assert len(events) == 1
    assert events[0].kind == "first_login"
    assert events[0].level == EventLevel.warn
    assert events[0].message == "Требуется подтверждение Instagram"


def test_first_login_skips_playwright_when_session_exists(
    db_session, make_account, make_proxy, monkeypatch
):
    from app.db.models import Event

    proxy = make_proxy(label="px-saved")
    account = make_account(username="saveduser", proxy=proxy)
    account.session_id = "d" * 40
    db_session.commit()

    monkeypatch.setattr(
        "app.accounts.first_login_service.playwright_browsers_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.accounts.first_login_service.storage_state_has_session",
        lambda username: False,
    )

    def _fail_first_login(**kwargs):
        raise AssertionError("first_login should not run when session already exists")

    monkeypatch.setattr("app.accounts.first_login_service.first_login", _fail_first_login)
    out = run_account_first_login(account, db_session)
    assert out.ok is True
    assert out.session_imported is True
    assert any("повторный автовход не нужен" in line.message.lower() for line in out.logs)
    assert not db_session.query(Event).filter(Event.kind == "first_login").all()


def test_first_login_skips_when_playwright_state_only(
    db_session, make_account, make_proxy, monkeypatch
):
    from app.db.models import Event

    proxy = make_proxy(label="px-pw-only")
    account = make_account(username="pwonly", proxy=proxy)
    db_session.commit()

    monkeypatch.setattr(
        "app.accounts.first_login_service.playwright_browsers_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.accounts.first_login_service.storage_state_has_session",
        lambda username: username == "pwonly",
    )
    monkeypatch.setattr(
        "app.accounts.first_login_service.import_playwright_session_to_account",
        lambda db, acc, **kwargs: True,
    )

    def _fail_first_login(**kwargs):
        raise AssertionError("first_login should not run when Playwright session exists")

    monkeypatch.setattr("app.accounts.first_login_service.first_login", _fail_first_login)
    out = run_account_first_login(account, db_session)
    assert out.ok is True
    assert not db_session.query(Event).filter(Event.kind == "first_login").all()


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
    out = run_account_first_login(account, db_session)
    assert out.ok is True
    assert captured["timezone_id"] == "America/New_York"
    db_session.refresh(account)
    assert account.timezone == "America/New_York"


def test_first_login_service_keeps_explicit_account_timezone(
    db_session, make_account, make_proxy, monkeypatch
):
    proxy = make_proxy(label="px-tz2", country="DE", timezone="Europe/Berlin")
    account = make_account(username="tzkeep", proxy=proxy, timezone="Europe/Moscow")

    monkeypatch.setattr(
        "app.accounts.first_login_service.playwright_browsers_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.accounts.first_login_service.first_login",
        lambda **kwargs: FirstLoginResult(ok=True, session_id="f" * 40),
    )
    monkeypatch.setattr(
        "app.accounts.first_login_service.import_playwright_session_to_account",
        lambda db, acc, **kwargs: True,
    )
    out = run_account_first_login(account, db_session)
    assert out.ok is True
    db_session.refresh(account)
    assert account.timezone == "Europe/Moscow"


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
    account_logs = [line.message for line in out.logs if line.step == "account"]
    assert any("Пароль:" in m for m in account_logs)
    assert any("Логин Instagram:" in m for m in account_logs)
    from app.db.models import Event, EventLevel

    events = db_session.query(Event).filter(Event.account_id == account.id).all()
    assert len(events) == 1
    assert events[0].kind == "first_login"
    assert events[0].level == EventLevel.error
    assert events[0].message and "Неверный пароль" in events[0].message
    assert "hunter" not in events[0].message.lower()


def test_first_login_service_guest_explore_error_and_bad_password(
    db_session, make_account, make_proxy, monkeypatch
):
    from app.accounts.session_manager import AuthenticationError

    proxy = make_proxy(label="px-guest")
    account = make_account(username="guestpw", proxy=proxy, password="wrong")

    monkeypatch.setattr(
        "app.accounts.first_login_service.playwright_browsers_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.accounts.first_login_service.first_login",
        lambda **kwargs: FirstLoginResult(
            ok=False,
            error=(
                "Вход не выполнен — открыт гостевой Explore без sessionid. "
                "Скорее всего неверный пароль или логин."
            ),
            page_url="https://www.instagram.com/explore/",
            login_debug_saved=True,
        ),
    )
    monkeypatch.setattr(
        "app.accounts.first_login_service.login_and_export_sessionid",
        lambda *a, **k: (_ for _ in ()).throw(AuthenticationError("bad password")),
    )

    out = run_account_first_login(account, db_session)
    assert out.ok is False
    assert out.error == "Неверный пароль — обновите пароль аккаунта в панели"
    login_msgs = [line.message for line in out.logs if line.step == "login"]
    assert any("гостевой Explore" in m for m in login_msgs)


def test_first_login_service_account_not_found_retries_email(
    db_session, make_account, make_proxy, monkeypatch
):
    from app.accounts.session_manager import AuthenticationError

    proxy = make_proxy(label="px-email")
    account = make_account(username="geuser", proxy=proxy)
    account.email = "real@example.com"
    db_session.commit()

    calls: list[str | None] = []

    def _fake_api_login(
        username,
        password,
        fingerprint,
        proxy_url,
        *,
        totp_seed=None,
        login_identifier=None,
        **kwargs,
    ):
        calls.append(login_identifier)
        if login_identifier == "geuser":
            raise AuthenticationError("We can't find an account with geuser")
        if login_identifier == "real@example.com":
            return "a" * 40
        raise AuthenticationError("unexpected login id")

    monkeypatch.setattr(
        "app.accounts.first_login_service.playwright_browsers_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.accounts.first_login_service.first_login",
        lambda **kwargs: FirstLoginResult(ok=False, error="no sessionid"),
    )
    monkeypatch.setattr(
        "app.accounts.first_login_service.login_and_export_sessionid",
        _fake_api_login,
    )
    out = run_account_first_login(account, db_session)
    assert out.ok is True
    assert calls == ["geuser", "real@example.com"]
    db_session.refresh(account)
    assert account.session_id == "a" * 40


def test_first_login_service_passes_login_identifier_to_playwright(
    db_session, make_account, make_proxy, monkeypatch
):
    proxy = make_proxy(label="px-lid")
    account = make_account(username="paneluser", proxy=proxy)
    account.login_identifier = "login@example.com"
    db_session.commit()
    captured: dict = {}

    monkeypatch.setattr(
        "app.accounts.first_login_service.playwright_browsers_available",
        lambda: True,
    )

    def _fake_first_login(**kwargs):
        captured.update(kwargs)
        return FirstLoginResult(ok=True, session_id="b" * 40)

    monkeypatch.setattr("app.accounts.first_login_service.first_login", _fake_first_login)
    monkeypatch.setattr(
        "app.accounts.first_login_service.import_playwright_session_to_account",
        lambda db, acc, **kwargs: True,
    )
    out = run_account_first_login(account, db_session)
    assert out.ok is True
    assert captured.get("login_identifier") == "login@example.com"


def test_first_login_service_passes_surface_to_playwright(
    db_session, make_account, make_proxy, monkeypatch
):
    proxy = make_proxy(label="px-surface")
    account = make_account(username="surfaceuser", proxy=proxy)
    db_session.commit()
    captured: dict = {}

    monkeypatch.setattr(
        "app.accounts.first_login_service.playwright_browsers_available",
        lambda: True,
    )

    def _fake_first_login(**kwargs):
        captured.update(kwargs)
        return FirstLoginResult(ok=True, session_id="b" * 40)

    monkeypatch.setattr("app.accounts.first_login_service.first_login", _fake_first_login)
    monkeypatch.setattr(
        "app.accounts.first_login_service.import_playwright_session_to_account",
        lambda db, acc, **kwargs: True,
    )
    out = run_account_first_login(account, db_session, surface="desktop")
    assert out.ok is True
    assert captured.get("surface") == "desktop"
    db_session.refresh(account)
    assert account.login_surface == "desktop"


def test_first_login_service_no_playwright(db_session, make_account, monkeypatch):
    account = make_account(username="nopw")

    monkeypatch.setattr(
        "app.accounts.first_login_service.playwright_browsers_available",
        lambda: False,
    )

    out = run_account_first_login(account, db_session)
    assert out.ok is False
    assert "install-playwright" in (out.error or "").lower() or "Chromium" in (out.error or "")


def test_first_login_uses_attached_proxy_url(db_session, make_account, make_proxy, monkeypatch):
    from app.assistant.tools import attach_proxy
    from app.db.models import Event

    proxy_a = make_proxy(label="px-chain-a", url="http://user:secret@proxy-a.example:8000")
    proxy_b = make_proxy(label="px-chain-b", url="http://user:secret@proxy-b.example:9000")
    account = make_account(username="pxchain", proxy=proxy_a, password="hunter2")
    captured: dict = {}

    monkeypatch.setattr(
        "app.accounts.first_login_service.playwright_browsers_available",
        lambda: True,
    )

    def _fake_first_login(**kwargs):
        captured["proxy_url"] = kwargs["proxy_url"]
        return FirstLoginResult(ok=True, session_id="a" * 40)

    monkeypatch.setattr("app.accounts.first_login_service.first_login", _fake_first_login)
    monkeypatch.setattr(
        "app.accounts.first_login_service.import_playwright_session_to_account",
        lambda db, acc, **kwargs: True,
    )
    monkeypatch.setattr(
        "app.accounts.first_login_service.storage_state_has_session",
        lambda username: False,
    )

    out = run_account_first_login(account, db_session)
    assert out.ok is True
    assert captured["proxy_url"] == proxy_a.url
    blob = " ".join(line.message for line in out.logs)
    assert "proxy-a.example:8000" in blob
    assert "user:secret" not in blob

    attach_proxy(db_session, account.id, "px-chain-b")
    db_session.refresh(account)
    out_b = run_account_first_login(account, db_session)
    assert out_b.ok is True
    assert captured["proxy_url"] == proxy_b.url
    blob_b = " ".join(line.message for line in out_b.logs)
    assert "proxy-b.example:9000" in blob_b
    assert "user:secret" not in blob_b
    assert not db_session.query(Event).filter(Event.kind == "first_login").all()


def test_first_login_fail_writes_event(db_session, make_account, monkeypatch):
    from app.db.models import Event, EventLevel

    account = make_account(username="flfail")
    monkeypatch.setattr(
        "app.accounts.first_login_service.playwright_browsers_available",
        lambda: False,
    )
    out = run_account_first_login(account, db_session)
    assert out.ok is False
    events = db_session.query(Event).filter(Event.account_id == account.id).all()
    assert len(events) == 1
    assert events[0].kind == "first_login"
    assert events[0].level == EventLevel.error
    assert "password" not in (events[0].message or "").lower()
    assert "hunter" not in (events[0].message or "")


def test_first_login_without_proxy_fails_before_browser(db_session, make_account, monkeypatch):
    from app.db.models import Event, EventLevel

    account = make_account(username="noproxyfl")
    account.proxy_id = None
    db_session.commit()
    monkeypatch.setattr(
        "app.accounts.first_login_service.playwright_browsers_available",
        lambda: True,
    )

    def _fail_browser(**kwargs):
        raise AssertionError("Playwright must not start without a proxy")

    monkeypatch.setattr("app.accounts.first_login_service.first_login", _fail_browser)
    out = run_account_first_login(account, db_session)
    assert out.ok is False
    assert out.error == "Прокси не назначен"
    events = db_session.query(Event).filter(Event.account_id == account.id).all()
    assert len(events) == 1
    assert events[0].kind == "first_login"
    assert events[0].level == EventLevel.error
    assert events[0].message == "Прокси не назначен"


def test_api_login_session_id_uses_email_handler(make_account, make_proxy, monkeypatch):
    from app.accounts.first_login_service import _api_login_session_id

    proxy = make_proxy(label="px-api")
    account = make_account(username="apiuser", proxy=proxy)
    account.email = "buyer@onet.pl"
    account.email_password = "mail-secret"
    account.imap_host = "imap.custom.test"
    captured: dict = {}

    def _fake_make_handler(username, **kwargs):
        captured.update(kwargs)
        return lambda _choice: "123456"

    def _fake_export(*args, **kwargs):
        captured["export"] = True
        return "e" * 40

    monkeypatch.setattr("app.accounts.challenge.make_handler", _fake_make_handler)
    monkeypatch.setattr(
        "app.accounts.first_login_service.login_and_export_sessionid",
        _fake_export,
    )

    sid = _api_login_session_id(
        account,
        object(),
        proxy,
        login_identifier=account.username,
    )
    assert sid == "e" * 40
    assert captured["email"] == "buyer@onet.pl"
    assert captured["email_password"] == "mail-secret"
    assert captured["imap_host"] == "imap.custom.test"
