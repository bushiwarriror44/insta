"""Tests for account connection diagnostics."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.accounts.connection_test import run_account_connection_test
from app.accounts.device_factory import generate_fingerprint
from app.accounts.session_manager import ProbeSessionResult, session_path
from app.db import Account
from app.proxies.pool import HealthSnapshot


@pytest.fixture()
def api_client(app_env, monkeypatch):
    from app.api import deps as api_deps
    from app.api.main import create_app
    from app.config import settings

    monkeypatch.setattr(settings, "admin_token", "", raising=True)
    monkeypatch.setattr("app.proxies.pool.health_check", lambda *a, **kw: {"ip": "203.0.113.5"})
    monkeypatch.setattr(
        "app.api.routes.accounts.ensure_fingerprint_and_proxy",
        lambda username, country="US", **kwargs: object(),
    )

    app = create_app()

    def _override_get_db():
        db = app_env.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[api_deps.get_db] = _override_get_db
    return TestClient(app)


@pytest.fixture()
def fingerprint(app_env):
    return generate_fingerprint("US")


def _make_account(db_session, *, username="connuser", proxy=None, session_id=None):
    account = Account(username=username, password="secret")
    if proxy is not None:
        account.proxy_id = proxy.id
    if session_id is not None:
        account.session_id = session_id
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)
    return account


def test_connection_test_404_via_api(api_client):
    res = api_client.post("/api/accounts/missing-user/test-connection")
    assert res.status_code == 404


def test_connection_test_happy_path_cookies_only(api_client, db_session, monkeypatch):
    api_client.post(
        "/api/proxies",
        json={"label": "px-conn", "url": "http://u:p@h:1", "skip_health_check": True},
    )
    api_client.post(
        "/api/accounts",
        json={
            "username": "happy",
            "password": "secret",
            "proxy_label": "px-conn",
            "session_id": "h" * 40,
        },
    )
    snapshot = HealthSnapshot(
        ok=True,
        ip="1.2.3.4",
        country="US",
        instagram_reachable=True,
        instagram_login_reachable=True,
        checked_at=datetime.now(timezone.utc),
    )

    monkeypatch.setattr(
        "app.accounts.connection_test.health_check_record",
        lambda db, proxy: (True, snapshot, None),
    )
    probe = MagicMock()
    monkeypatch.setattr("app.accounts.connection_test.probe_session_auth", probe)

    res = api_client.post("/api/accounts/happy/test-connection")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["overall_ok"] is True
    assert body["proxy_health"]["ok"] is True
    assert body["instagram_auth"]["ok"] is True
    assert body["instagram_auth"]["method"] == "sessionid"
    probe.assert_not_called()
    assert any(
        "Mobile API-проверка пропущена" in line["message"] for line in body["logs"]
    )


def test_connection_test_mobile_probe_path(api_client, monkeypatch):
    api_client.post(
        "/api/proxies",
        json={"label": "px-mob", "url": "http://u:p@h:1", "skip_health_check": True},
    )
    api_client.post(
        "/api/accounts",
        json={
            "username": "mobprobe",
            "password": "secret",
            "proxy_label": "px-mob",
            "session_id": "m" * 40,
        },
    )
    snapshot = HealthSnapshot(
        ok=True,
        ip="1.2.3.4",
        country="US",
        instagram_reachable=True,
        instagram_login_reachable=True,
        checked_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        "app.accounts.connection_test.health_check_record",
        lambda db, proxy: (True, snapshot, None),
    )
    monkeypatch.setattr(
        "app.accounts.connection_test.ensure_fingerprint_and_proxy",
        lambda username, country="US", **kwargs: MagicMock(),
    )
    monkeypatch.setattr(
        "app.accounts.connection_test.probe_session_auth",
        lambda **kwargs: ProbeSessionResult(
            ok=True,
            method="sessionid",
            ig_username="mobprobe",
        ),
    )

    res = api_client.post(
        "/api/accounts/mobprobe/test-connection",
        params={"probe_mobile": "true"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["overall_ok"] is True
    assert body["instagram_auth"]["ig_username"] == "mobprobe"


def test_connection_test_proxy_unhealthy_skips_auth(api_client, monkeypatch):
    api_client.post(
        "/api/proxies",
        json={"label": "px-bad", "url": "http://u:p@h:2", "skip_health_check": True},
    )
    api_client.post(
        "/api/accounts",
        json={"username": "badproxy", "password": "secret", "proxy_label": "px-bad"},
    )
    probe = MagicMock()
    monkeypatch.setattr(
        "app.accounts.connection_test.health_check_record",
        lambda db, proxy: (False, None, "Proxy unhealthy"),
    )
    monkeypatch.setattr("app.accounts.connection_test.probe_session_auth", probe)

    res = api_client.post("/api/accounts/badproxy/test-connection")
    assert res.status_code == 200
    body = res.json()
    assert body["overall_ok"] is False
    assert body["proxy_health"]["ok"] is False
    assert "unhealthy" in (body["proxy_health"]["error"] or "").lower()
    probe.assert_not_called()


def test_connection_test_session_auth_failure(api_client, monkeypatch):
    api_client.post(
        "/api/proxies",
        json={"label": "px-sess", "url": "http://u:p@h:3", "skip_health_check": True},
    )
    api_client.post(
        "/api/accounts",
        json={"username": "nosess", "password": "secret", "proxy_label": "px-sess"},
    )
    snapshot = HealthSnapshot(
        ok=True,
        ip="5.6.7.8",
        country="DE",
        instagram_reachable=True,
        instagram_login_reachable=True,
        checked_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        "app.accounts.connection_test.health_check_record",
        lambda db, proxy: (True, snapshot, None),
    )
    monkeypatch.setattr(
        "app.accounts.connection_test.ensure_fingerprint_and_proxy",
        lambda username, country="US", **kwargs: MagicMock(),
    )
    monkeypatch.setattr(
        "app.accounts.connection_test.probe_session_auth",
        lambda **kwargs: ProbeSessionResult(
            ok=False,
            method="none",
            error="No session_id in database and no session file on disk",
            error_code="session_missing",
        ),
    )

    # cookies-only: missing session without calling mobile probe
    res = api_client.post("/api/accounts/nosess/test-connection")
    body = res.json()
    assert body["overall_ok"] is False
    assert body["instagram_auth"]["ok"] is False
    assert body["instagram_auth"]["error_code"] == "session_missing"

    # mobile probe path still invokes probe_session_auth
    res_m = api_client.post(
        "/api/accounts/nosess/test-connection",
        params={"probe_mobile": "true"},
    )
    body_m = res_m.json()
    assert body_m["overall_ok"] is False
    assert body_m["instagram_auth"]["ok"] is False


def test_accounts_list_includes_session_file_metadata(api_client, app_env):
    api_client.post(
        "/api/proxies",
        json={"label": "px-meta2", "url": "http://u:p@h:1", "skip_health_check": True},
    )
    api_client.post(
        "/api/accounts",
        json={"username": "filemeta", "password": "secret", "proxy_label": "px-meta2"},
    )
    path = session_path("filemeta")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"cookies": {"sessionid": "x" * 40}}', encoding="utf-8")

    res = api_client.get("/api/accounts")
    body = next(a for a in res.json() if a["username"] == "filemeta")
    assert body["session_file_exists"] is True
    assert body["session_file_updated_at"] is not None
    assert body["session_source"] in ("session_file", "none")


def test_proxy_check_returns_instagram_reachable(api_client, monkeypatch):
    api_client.post(
        "/api/proxies",
        json={"label": "px-ig", "url": "http://u:p@h:9", "skip_health_check": True},
    )
    snapshot = HealthSnapshot(
        ok=True,
        ip="9.9.9.9",
        country="US",
        instagram_reachable=True,
        instagram_login_reachable=True,
        checked_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        "app.api.routes.proxies.health_check_record",
        lambda db, proxy: (True, snapshot, None),
    )
    res = api_client.post("/api/proxies/px-ig/check")
    assert res.status_code == 200
    body = res.json()
    assert body["instagram_reachable"] is True
    assert body["geo_mismatch_warning"] is False


def test_run_account_connection_test_no_proxy(db_session, make_proxy):
    make_proxy()
    account = _make_account(db_session, username="noprx", proxy=None)
    result = run_account_connection_test(account, db_session)
    assert result.overall_ok is False
    assert result.proxy_assigned is False
    assert result.run_id > 0
    assert any(line.step == "proxy" for line in result.logs)
    assert any(line.step == "account" for line in result.logs)
    assert any("Пароль:" in line.message for line in result.logs if line.step == "account")


def test_diagnostic_runs_list_after_connection_test(api_client, monkeypatch):
    api_client.post(
        "/api/proxies",
        json={"label": "px-diag", "url": "http://u:p@h:1", "skip_health_check": True},
    )
    api_client.post(
        "/api/accounts",
        json={"username": "diaglist", "password": "secret", "proxy_label": "px-diag"},
    )
    snapshot = HealthSnapshot(
        ok=True,
        ip="1.2.3.4",
        country="US",
        instagram_reachable=True,
        instagram_login_reachable=True,
        checked_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        "app.accounts.connection_test.health_check_record",
        lambda db, proxy: (True, snapshot, None),
    )
    monkeypatch.setattr(
        "app.accounts.connection_test.ensure_fingerprint_and_proxy",
        lambda username, country="US", **kwargs: MagicMock(),
    )
    monkeypatch.setattr(
        "app.accounts.connection_test.probe_session_auth",
        lambda **kwargs: ProbeSessionResult(ok=True, method="sessionid", ig_username="diaglist"),
    )
    test_res = api_client.post("/api/accounts/diaglist/test-connection")
    run_id = test_res.json()["run_id"]

    list_res = api_client.get("/api/diagnostic-runs", params={"username": "diaglist"})
    assert list_res.status_code == 200
    rows = list_res.json()
    assert len(rows) >= 1
    assert rows[0]["id"] == run_id

    get_res = api_client.get(f"/api/diagnostic-runs/{run_id}")
    assert get_res.status_code == 200
    assert get_res.json()["logs"]


def test_probe_session_auth_none_without_credentials(app_env, fingerprint, fake_client_class):
    from app.accounts.session_manager import probe_session_auth

    result = probe_session_auth(
        "nobody",
        fingerprint,
        "http://p:1",
        session_id=None,
    )
    assert result.ok is False
    assert result.method == "none"


def test_youtube_connection_ok_without_instagram_reach(db_session, make_account, monkeypatch, app_env):
    from datetime import datetime, timezone

    from app.accounts.connection_test import run_account_connection_test
    from app.accounts.playwright_session import save_playwright_state
    from app.db.models import Platform
    from app.proxies.pool import HealthSnapshot

    account = make_account(username="ytconn", platform=Platform.youtube)
    save_playwright_state(
        "ytconn",
        {"cookies": [{"name": "SID", "value": "x", "domain": ".youtube.com"}], "origins": []},
    )
    snapshot = HealthSnapshot(
        ok=True,
        ip="1.2.3.4",
        country="US",
        instagram_reachable=False,
        instagram_login_reachable=False,
        checked_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        "app.accounts.connection_test.health_check_record",
        lambda db, proxy: (True, snapshot, None),
    )
    out = run_account_connection_test(account, db_session)
    assert out.overall_ok is True
    assert out.instagram_auth.method == "playwright"
    assert out.session_storage.session_source == "playwright"


def test_youtube_connection_fails_without_state(db_session, make_account, monkeypatch):
    from datetime import datetime, timezone

    from app.accounts.connection_test import run_account_connection_test
    from app.db.models import Platform
    from app.proxies.pool import HealthSnapshot

    account = make_account(username="ytnone", platform=Platform.youtube)
    snapshot = HealthSnapshot(
        ok=True,
        ip="1.2.3.4",
        country="US",
        instagram_reachable=False,
        instagram_login_reachable=False,
        checked_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        "app.accounts.connection_test.health_check_record",
        lambda db, proxy: (True, snapshot, None),
    )
    out = run_account_connection_test(account, db_session)
    assert out.overall_ok is False
    assert out.instagram_auth.error_code == "session_missing"


def test_connection_test_passes_attached_proxy_url(db_session, make_account, make_proxy, monkeypatch):
    from app.accounts.connection_test import run_account_connection_test
    from app.accounts.session_manager import ProbeSessionResult
    from app.proxies.pool import HealthSnapshot

    proxy = make_proxy(label="px-ct-url", url="http://user:secret@egress.example:7777")
    account = make_account(username="ctproxy", proxy=proxy, session_id="s" * 40)
    captured: dict = {}
    snapshot = HealthSnapshot(
        ok=True,
        ip="203.0.113.9",
        country="US",
        instagram_reachable=True,
        instagram_login_reachable=True,
        checked_at=datetime.now(timezone.utc),
    )

    def _health(db, px):
        captured["health_url"] = px.url
        return True, snapshot, None

    def _probe(**kwargs):
        captured["probe_url"] = kwargs["proxy_url"]
        return ProbeSessionResult(ok=True, method="sessionid", ig_username="ctproxy")

    monkeypatch.setattr("app.accounts.connection_test.health_check_record", _health)
    monkeypatch.setattr(
        "app.accounts.connection_test.ensure_fingerprint_and_proxy",
        lambda username, country="US", **kwargs: MagicMock(),
    )
    monkeypatch.setattr("app.accounts.connection_test.probe_session_auth", _probe)

    out = run_account_connection_test(account, db_session, probe_mobile=True)
    assert out.overall_ok is True
    assert captured["health_url"] == proxy.url
    assert captured["probe_url"] == proxy.url
    blob = " ".join(line.message for line in out.logs)
    assert "egress.example:7777" in blob
    assert "user:secret" not in blob


def test_connection_test_fail_writes_event(db_session, make_account):
    from app.accounts.connection_test import run_account_connection_test
    from app.db.models import Event, EventLevel

    account = make_account(username="nopx")
    account.proxy_id = None
    db_session.commit()
    out = run_account_connection_test(account, db_session)
    assert out.overall_ok is False
    events = db_session.query(Event).filter(Event.account_id == account.id).all()
    assert len(events) == 1
    assert events[0].kind == "connection_test"
    assert events[0].level == EventLevel.error
