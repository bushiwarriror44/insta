"""Smoke tests for the FastAPI admin endpoints."""
from __future__ import annotations

import io
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def api_client(app_env, monkeypatch):
    """Build a FastAPI TestClient with the test SessionLocal wired in."""
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
def auth_client(app_env, monkeypatch):
    """Same as ``api_client`` but with ADMIN_TOKEN configured."""
    from app.api import deps as api_deps
    from app.api.main import create_app
    from app.config import settings

    monkeypatch.setattr(settings, "admin_token", "secret-token", raising=True)
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


def test_health_endpoint_open_mode(api_client):
    res = api_client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["auth_required"] is False
    assert "version" in body


def test_dashboard_open_mode_returns_summary(api_client):
    res = api_client.get("/api/dashboard")
    assert res.status_code == 200
    body = res.json()
    for key in (
        "accounts_total",
        "accounts_active",
        "proxies_total",
        "jobs_queued",
        "jobs_running",
        "daily_stats",
        "recent_events",
    ):
        assert key in body


def test_auth_required_when_token_set(auth_client):
    res = auth_client.get("/api/dashboard")
    assert res.status_code == 401

    res = auth_client.get("/api/dashboard", headers={"Authorization": "Bearer wrong"})
    assert res.status_code == 401

    res = auth_client.get(
        "/api/dashboard", headers={"Authorization": "Bearer secret-token"}
    )
    assert res.status_code == 200


def test_health_is_unauth_even_with_token(auth_client):
    res = auth_client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["auth_required"] is True


def test_proxies_create_and_list(api_client):
    payload = {
        "label": "res-eu-1",
        "url": "http://u:p@example.com:8000",
        "country": "DE",
        "timezone": "Europe/Berlin",
        "skip_health_check": True,
    }
    res = api_client.post("/api/proxies", json=payload)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["label"] == "res-eu-1"
    assert body.get("accounts_count", 0) == 0

    res = api_client.get("/api/proxies")
    assert res.status_code == 200
    items = res.json()
    assert any(p["label"] == "res-eu-1" and p.get("accounts_count", 0) == 0 for p in items)


def test_proxies_update(api_client):
    api_client.post(
        "/api/proxies",
        json={"label": "px-upd", "url": "http://a:b@old:1", "skip_health_check": True},
    )
    res = api_client.put(
        "/api/proxies/px-upd",
        json={
            "url": "http://a:b@new:2",
            "country": "US",
            "timezone": "America/New_York",
            "notes": "n",
            "skip_health_check": True,
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["url"] == "http://a:b@new:2"
    assert data["country"] == "US"
    assert data["timezone"] == "America/New_York"


def test_proxies_delete(api_client):
    api_client.post(
        "/api/proxies",
        json={"label": "px-del", "url": "http://u:p@h:1", "skip_health_check": True},
    )
    res = api_client.delete("/api/proxies/px-del")
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    res = api_client.get("/api/proxies")
    assert not any(p["label"] == "px-del" for p in res.json())


def test_proxies_delete_blocked_when_in_use(api_client):
    api_client.post(
        "/api/proxies",
        json={"label": "px-busy", "url": "http://u:p@h:1", "skip_health_check": True},
    )
    api_client.post(
        "/api/accounts",
        json={"username": "u1", "password": "p", "proxy_label": "px-busy"},
    )
    res = api_client.delete("/api/proxies/px-busy")
    assert res.status_code == 409
    assert "account" in res.json()["detail"].lower()


def test_accounts_create_autofills_timezone_from_proxy(api_client):
    api_client.post(
        "/api/proxies",
        json={
            "label": "px-pl",
            "url": "http://u:p@h:1",
            "country": "PL",
            "timezone": "Europe/Warsaw",
            "skip_health_check": True,
        },
    )
    res = api_client.post(
        "/api/accounts",
        json={
            "username": "tzfill",
            "password": "secret",
            "proxy_label": "px-pl",
            "timezone": "UTC",
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["timezone"] == "Europe/Warsaw"


def test_accounts_create_keeps_explicit_timezone(api_client):
    api_client.post(
        "/api/proxies",
        json={
            "label": "px-de-tz",
            "url": "http://u:p@h:1",
            "country": "DE",
            "timezone": "Europe/Berlin",
            "skip_health_check": True,
        },
    )
    res = api_client.post(
        "/api/accounts",
        json={
            "username": "tzkeep",
            "password": "secret",
            "proxy_label": "px-de-tz",
            "timezone": "Europe/Moscow",
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["timezone"] == "Europe/Moscow"


def test_accounts_update_proxy_syncs_timezone(api_client):
    api_client.post(
        "/api/proxies",
        json={
            "label": "px-a",
            "url": "http://u:p@a:1",
            "country": "US",
            "timezone": "America/New_York",
            "skip_health_check": True,
        },
    )
    api_client.post(
        "/api/proxies",
        json={
            "label": "px-b",
            "url": "http://u:p@b:1",
            "country": "PL",
            "timezone": "Europe/Warsaw",
            "skip_health_check": True,
        },
    )
    api_client.post(
        "/api/accounts",
        json={
            "username": "tzmove",
            "password": "secret",
            "proxy_label": "px-a",
            "timezone": "America/New_York",
        },
    )
    res = api_client.put("/api/accounts/tzmove/proxy", json={"proxy_label": "px-b"})
    assert res.status_code == 200, res.text
    assert res.json()["timezone"] == "Europe/Warsaw"


def test_accounts_create_pause_resume(api_client):
    api_client.post(
        "/api/proxies",
        json={"label": "res-1", "url": "http://u:p@h:1", "skip_health_check": True},
    )

    res = api_client.post(
        "/api/accounts",
        json={
            "username": "alice",
            "password": "secret",
            "proxy_label": "res-1",
            "timezone": "UTC",
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["username"] == "alice"
    assert body["status"] == "active"
    assert body["proxy_label"] == "res-1"

    res = api_client.post("/api/accounts/alice/pause")
    assert res.status_code == 200
    assert res.json()["status"] == "paused"

    res = api_client.post("/api/accounts/alice/resume")
    assert res.status_code == 200
    assert res.json()["status"] == "active"

    res = api_client.get("/api/accounts")
    assert res.status_code == 200
    assert any(a["username"] == "alice" for a in res.json())


def test_accounts_update_proxy_reassigns_account_and_counts(api_client):
    api_client.post(
        "/api/proxies",
        json={"label": "px-old", "url": "http://u:p@old:1", "skip_health_check": True},
    )
    api_client.post(
        "/api/proxies",
        json={"label": "px-new", "url": "http://u:p@new:1", "skip_health_check": True},
    )
    api_client.post(
        "/api/accounts",
        json={"username": "alice", "password": "secret", "proxy_label": "px-old"},
    )

    res = api_client.put("/api/accounts/alice/proxy", json={"proxy_label": "px-new"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["username"] == "alice"
    assert body["proxy_label"] == "px-new"

    proxies = api_client.get("/api/proxies").json()
    counts = {p["label"]: p["accounts_count"] for p in proxies}
    assert counts["px-old"] == 0
    assert counts["px-new"] == 1

    res = api_client.delete("/api/proxies/px-old")
    assert res.status_code == 200


def test_accounts_update_proxy_rejects_missing_account(api_client):
    api_client.post(
        "/api/proxies",
        json={"label": "px-one", "url": "http://u:p@h:1", "skip_health_check": True},
    )
    res = api_client.put("/api/accounts/missing/proxy", json={"proxy_label": "px-one"})
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_accounts_create_with_session_id_sets_has_session_id(api_client):
    api_client.post(
        "/api/proxies",
        json={"label": "px-sid", "url": "http://u:p@h:1", "skip_health_check": True},
    )
    session_id = "a" * 40
    res = api_client.post(
        "/api/accounts",
        json={
            "username": "siduser",
            "password": "secret",
            "proxy_label": "px-sid",
            "session_id": session_id,
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["has_session_id"] is True
    assert "session_id" not in body


def test_accounts_update_session_success(api_client):
    api_client.post(
        "/api/proxies",
        json={"label": "px-sess", "url": "http://u:p@h:1", "skip_health_check": True},
    )
    api_client.post(
        "/api/accounts",
        json={"username": "bob", "password": "secret", "proxy_label": "px-sess"},
    )
    session_id = "b" * 40
    res = api_client.put("/api/accounts/bob/session", json={"session_id": session_id})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["username"] == "bob"
    assert body["has_session_id"] is True
    assert "session_id" not in body


def test_accounts_update_session_decodes_url_encoded(api_client, app_env):
    from app.db import Account, SessionLocal

    api_client.post(
        "/api/proxies",
        json={"label": "px-enc", "url": "http://u:p@h:1", "skip_health_check": True},
    )
    api_client.post(
        "/api/accounts",
        json={"username": "encuser", "password": "secret", "proxy_label": "px-enc"},
    )
    encoded = "38945170646%3AG5p9NNhoGGVDGE%3A20%3AAYhWdcBsbiU0mVgtsM9jvb0aRWnNqazSIs__yXPUMw"
    res = api_client.put("/api/accounts/encuser/session", json={"session_id": encoded})
    assert res.status_code == 200, res.text
    with SessionLocal() as db:
        row = db.query(Account).filter_by(username="encuser").one()
        assert "%3A" not in (row.session_id or "")
        assert (row.session_id or "").startswith("38945170646:")


def test_accounts_update_session_rejects_missing_account(api_client):
    res = api_client.put(
        "/api/accounts/missing/session",
        json={"session_id": "c" * 40},
    )
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_accounts_get_session_from_database(api_client):
    api_client.post(
        "/api/proxies",
        json={"label": "px-get", "url": "http://u:p@h:1", "skip_health_check": True},
    )
    session_id = "e" * 40
    api_client.post(
        "/api/accounts",
        json={
            "username": "getter",
            "password": "secret",
            "proxy_label": "px-get",
            "session_id": session_id,
        },
    )
    res = api_client.get("/api/accounts/getter/session")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["session_id"] == session_id
    assert body["source"] == "database"

    listed = api_client.get("/api/accounts").json()
    alice = next(a for a in listed if a["username"] == "getter")
    assert "session_id" not in alice


def test_accounts_get_session_from_file(api_client, app_env):
    import json

    from app.accounts.session_manager import session_path

    api_client.post(
        "/api/proxies",
        json={"label": "px-file", "url": "http://u:p@h:1", "skip_health_check": True},
    )
    api_client.post(
        "/api/accounts",
        json={"username": "fileuser", "password": "secret", "proxy_label": "px-file"},
    )
    sid = "g" * 40
    path = session_path("fileuser")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"authorization_data": {"sessionid": sid}}), encoding="utf-8")

    res = api_client.get("/api/accounts/fileuser/session")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["session_id"] == sid
    assert body["source"] == "session_file"
    assert body["session_file_exists"] is True


def test_accounts_get_session_404_when_empty(api_client):
    api_client.post(
        "/api/proxies",
        json={"label": "px-empty", "url": "http://u:p@h:1", "skip_health_check": True},
    )
    api_client.post(
        "/api/accounts",
        json={"username": "empty", "password": "secret", "proxy_label": "px-empty"},
    )
    res = api_client.get("/api/accounts/empty/session")
    assert res.status_code == 404


def test_accounts_list_includes_proxy_metadata(api_client):
    api_client.post(
        "/api/proxies",
        json={
            "label": "px-meta",
            "url": "http://u:p@h:1",
            "country": "US",
            "skip_health_check": True,
        },
    )
    api_client.post(
        "/api/accounts",
        json={"username": "metauser", "password": "secret", "proxy_label": "px-meta"},
    )
    res = api_client.get("/api/accounts")
    body = next(a for a in res.json() if a["username"] == "metauser")
    assert body["proxy_country"] == "US"
    assert body["proxy_label"] == "px-meta"
    assert body["proxy_is_healthy"] is True


def test_accounts_update_session_clears_session_file(api_client, app_env):
    from app.accounts.session_manager import session_path

    api_client.post(
        "/api/proxies",
        json={"label": "px-clear", "url": "http://u:p@h:1", "skip_health_check": True},
    )
    api_client.post(
        "/api/accounts",
        json={"username": "clearuser", "password": "secret", "proxy_label": "px-clear"},
    )
    path = session_path("clearuser")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"cookies": {"sessionid": "old"}}', encoding="utf-8")

    session_id = "h" * 40
    res = api_client.put("/api/accounts/clearuser/session", json={"session_id": session_id})
    assert res.status_code == 200, res.text
    assert not path.exists()


def _create_account(api_client, username: str, proxy_label: str = "px-dolphin"):
    api_client.post(
        "/api/proxies",
        json={"label": proxy_label, "url": "http://u:p@h:1", "skip_health_check": True},
    )
    api_client.post(
        "/api/accounts",
        json={"username": username, "password": "secret", "proxy_label": proxy_label},
    )


def test_accounts_export_cookies(api_client, app_env):
    import json

    from app.accounts.playwright_session import playwright_state_path

    _create_account(api_client, "expuser", "px-exp")
    state_dir = playwright_state_path("expuser").parent
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state.json").write_text(
        json.dumps(
            {
                "cookies": [{"name": "sessionid", "value": "j" * 40, "domain": ".instagram.com"}],
                "origins": [],
            }
        ),
        encoding="utf-8",
    )
    res = api_client.get("/api/accounts/expuser/cookies/export")
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("application/json")
    body = res.json()
    assert isinstance(body, list)
    assert body[0]["name"] == "sessionid"


def test_accounts_export_cookies_404(api_client):
    _create_account(api_client, "noexp", "px-noexp")
    res = api_client.get("/api/accounts/noexp/cookies/export")
    assert res.status_code == 404


def test_accounts_export_playwright_state(api_client, app_env):
    import json

    from app.accounts.playwright_session import playwright_state_path

    _create_account(api_client, "pwexp", "px-pwexp")
    path = playwright_state_path("pwexp")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cookies": [], "origins": []}), encoding="utf-8")
    res = api_client.get("/api/accounts/pwexp/playwright-state")
    assert res.status_code == 200, res.text
    assert "application/json" in res.headers["content-type"]


def test_accounts_export_playwright_state_404(api_client):
    _create_account(api_client, "nopw", "px-nopw")
    res = api_client.get("/api/accounts/nopw/playwright-state")
    assert res.status_code == 404


def test_accounts_export_login_debug_screenshot(api_client, app_env):
    from app.accounts.playwright_session import login_debug_screenshot_path

    _create_account(api_client, "dbgexp", "px-dbgexp")
    path = login_debug_screenshot_path("dbgexp")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    res = api_client.get("/api/accounts/dbgexp/login-debug-screenshot")
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("image/png")


def test_accounts_export_login_debug_screenshot_404(api_client):
    _create_account(api_client, "nodbg", "px-nodbg")
    res = api_client.get("/api/accounts/nodbg/login-debug-screenshot")
    assert res.status_code == 404


def test_accounts_export_device_fingerprint(api_client, app_env):
    from app.accounts.device_factory import generate_fingerprint, save_fingerprint

    _create_account(api_client, "fpexp", "px-fpexp")
    save_fingerprint("fpexp", generate_fingerprint(country="US"))
    res = api_client.get("/api/accounts/fpexp/device-fingerprint")
    assert res.status_code == 200, res.text
    assert "application/json" in res.headers["content-type"]


def test_accounts_export_device_fingerprint_404(api_client):
    _create_account(api_client, "nofp", "px-nofp")
    res = api_client.get("/api/accounts/nofp/device-fingerprint")
    assert res.status_code == 404


def test_accounts_import_cookies_dolphin(api_client, app_env):
    import json

    from app.accounts.playwright_session import playwright_state_path

    _create_account(api_client, "impuser", "px-imp")
    sid = "k" * 40
    payload = json.dumps(
        [{"name": "sessionid", "value": sid, "domain": ".instagram.com"}]
    ).encode("utf-8")
    res = api_client.post(
        "/api/accounts/impuser/cookies/import",
        files={"file": ("cookies.json", io.BytesIO(payload), "application/json")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["format"] == "dolphin"
    assert body["session_id"] == sid
    assert body["session_id_imported"] is True
    assert playwright_state_path("impuser").exists()
    listed = api_client.get("/api/accounts").json()
    row = next(a for a in listed if a["username"] == "impuser")
    assert row["has_session_id"] is True


def test_accounts_import_cookies_txt_with_encoded_sessionid(api_client, app_env):
    import json

    from app.db import Account, SessionLocal

    _create_account(api_client, "txtimp", "px-txtimp")
    encoded = "38945170646%3AG5p9NNhoGGVDGE%3A20%3AAYhWdcBsbiU0mVgtsM9jvb0aRWnNqazSIs__yXPUMw"
    payload = json.dumps(
        [
            {"name": "AEC", "value": "x", "domain": ".google.com"},
            {"name": "sessionid", "value": encoded, "domain": ".instagram.com"},
        ]
    ).encode("utf-8")
    res = api_client.post(
        "/api/accounts/txtimp/cookies/import",
        files={"file": ("dolphin-anty-cookies-profile2.txt", io.BytesIO(payload), "text/plain")},
    )
    assert res.status_code == 200, res.text
    with SessionLocal() as db:
        row = db.query(Account).filter_by(username="txtimp").one()
        assert row.session_id is not None
        assert "%3A" not in row.session_id
        assert row.session_id.startswith("38945170646:")


def test_accounts_import_cookies_bad_format(api_client):
    _create_account(api_client, "badimp", "px-badimp")
    res = api_client.post(
        "/api/accounts/badimp/cookies/import",
        files={"file": ("bad.json", io.BytesIO(b'{"nope": true}'), "application/json")},
    )
    assert res.status_code == 400


def test_accounts_update_proxy_rejects_missing_proxy(api_client):
    api_client.post(
        "/api/proxies",
        json={"label": "px-one", "url": "http://u:p@h:1", "skip_health_check": True},
    )
    api_client.post(
        "/api/accounts",
        json={"username": "alice", "password": "secret", "proxy_label": "px-one"},
    )

    res = api_client.put("/api/accounts/alice/proxy", json={"proxy_label": "ghost"})
    assert res.status_code == 400
    assert "proxy" in res.json()["detail"].lower()


def test_accounts_patch_notes(api_client):
    api_client.post(
        "/api/proxies",
        json={"label": "px-notes", "url": "http://u:p@h:1", "skip_health_check": True},
    )
    api_client.post(
        "/api/accounts",
        json={
            "username": "notesuser",
            "password": "secret",
            "proxy_label": "px-notes",
            "notes": "initial note",
        },
    )

    listed = api_client.get("/api/accounts")
    row = next(a for a in listed.json() if a["username"] == "notesuser")
    assert row["notes"] == "initial note"

    patch = api_client.patch(
        "/api/accounts/notesuser/notes",
        json={"notes": "updated by admin"},
    )
    assert patch.status_code == 200
    assert patch.json()["notes"] == "updated by admin"

    clear = api_client.patch("/api/accounts/notesuser/notes", json={"notes": None})
    assert clear.status_code == 200
    assert clear.json()["notes"] is None


def test_accounts_create_rejects_missing_proxy(api_client):
    res = api_client.post(
        "/api/accounts",
        json={"username": "x", "password": "y", "proxy_label": "ghost"},
    )
    assert res.status_code == 400


def test_accounts_create_rejects_invalid_active_hours(api_client):
    api_client.post(
        "/api/proxies",
        json={"label": "res-3", "url": "http://u:p@h:3", "skip_health_check": True},
    )
    res = api_client.post(
        "/api/accounts",
        json={
            "username": "alice2",
            "password": "secret",
            "proxy_label": "res-3",
            "active_hour_start": 22,
            "active_hour_end": 22,
        },
    )
    assert res.status_code == 422
    assert "active_hour_end must be greater than active_hour_start" in res.text


def test_accounts_create_rejects_unknown_caption_profile(api_client):
    api_client.post(
        "/api/proxies",
        json={"label": "res-4", "url": "http://u:p@h:4", "skip_health_check": True},
    )
    res = api_client.post(
        "/api/accounts",
        json={
            "username": "alice3",
            "password": "secret",
            "proxy_label": "res-4",
            "caption_profile": "unknown-profile",
        },
    )
    assert res.status_code == 422
    assert "caption_profile must be one of" in res.text


def test_video_upload_list_and_enqueue(api_client, app_env):
    api_client.post(
        "/api/proxies",
        json={"label": "res-2", "url": "http://u:p@h:2", "skip_health_check": True},
    )
    api_client.post(
        "/api/accounts",
        json={"username": "bob", "password": "secret", "proxy_label": "res-2"},
    )

    payload = b"\x00" * 2048
    res = api_client.post(
        "/api/videos",
        files={"file": ("clip.mp4", io.BytesIO(payload), "video/mp4")},
    )
    assert res.status_code == 201, res.text
    upload = res.json()
    assert upload["filename"].endswith(".mp4")
    assert upload["size_bytes"] == len(payload)
    assert upload["media_type"] == "video"

    res = api_client.get("/api/videos")
    assert res.status_code == 200
    assert any(v["filename"] == upload["filename"] for v in res.json())

    when = datetime.now(timezone.utc).isoformat()
    res = api_client.post(
        "/api/jobs",
        json={
            "username": "bob",
            "media_filename": upload["filename"],
            "post_type": "reel",
            "when": when,
        },
    )
    assert res.status_code == 201, res.text
    job = res.json()
    assert job["status"] == "queued"
    assert job["account_username"] == "bob"
    assert job["post_type"] == "reel"

    res = api_client.get("/api/jobs", params={"username": "bob"})
    assert res.status_code == 200
    jobs = res.json()
    assert len(jobs) == 1
    assert jobs[0]["id"] == job["id"]

    res = api_client.post(f"/api/jobs/{job['id']}/cancel")
    assert res.status_code == 200
    assert res.json()["status"] == "cancelled"


def test_image_upload_and_feed_photo_enqueue(api_client):
    api_client.post(
        "/api/proxies",
        json={"label": "res-img", "url": "http://u:p@h:2", "skip_health_check": True},
    )
    api_client.post(
        "/api/accounts",
        json={"username": "imguser", "password": "secret", "proxy_label": "res-img"},
    )
    res = api_client.post(
        "/api/videos",
        files={"file": ("photo.jpg", io.BytesIO(b"jpg"), "image/jpeg")},
    )
    assert res.status_code == 201, res.text
    upload = res.json()
    assert upload["media_type"] == "image"

    res = api_client.post(
        "/api/jobs",
        json={
            "username": "imguser",
            "media_filename": upload["filename"],
            "post_type": "feed_photo",
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["post_type"] == "feed_photo"


def test_enqueue_rejects_wrong_media_type(api_client):
    api_client.post(
        "/api/proxies",
        json={"label": "res-wrong", "url": "http://u:p@h:2", "skip_health_check": True},
    )
    api_client.post(
        "/api/accounts",
        json={"username": "wronguser", "password": "secret", "proxy_label": "res-wrong"},
    )
    res = api_client.post(
        "/api/videos",
        files={"file": ("photo.png", io.BytesIO(b"png"), "image/png")},
    )
    upload = res.json()
    res = api_client.post(
        "/api/jobs",
        json={
            "username": "wronguser",
            "media_filename": upload["filename"],
            "post_type": "reel",
        },
    )
    assert res.status_code == 400
    assert "requires a video" in res.json()["detail"]


def test_publications_list_and_refresh_stats(api_client, db_session, make_account, monkeypatch):
    from app.db import PostJob, PostJobStatus, PostLog
    from app.publisher.reels_publisher import MediaStats

    account = make_account(username="statsuser")
    job = PostJob(
        account_id=account.id,
        source_video_path="data/videos/source/x.mp4",
        scheduled_for=datetime.now(timezone.utc),
        status=PostJobStatus.done,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    log = PostLog(
        job_id=job.id,
        account_id=account.id,
        success=True,
        media_id="MID",
        media_code="CODE",
        post_type="reel",
        final_video_path="data/videos/out/x.mp4",
        final_caption="cap",
    )
    db_session.add(log)
    db_session.commit()
    db_session.refresh(log)

    def _fake_refresh(db, row):
        row.view_count = 10
        row.like_count = 3
        row.comment_count = 1
        row.raw_stats_json = MediaStats(view_count=10).raw_json
        db.commit()
        db.refresh(row)
        return row

    monkeypatch.setattr("app.api.routes.publications.refresh_post_log_stats", _fake_refresh)

    res = api_client.get("/api/publications")
    assert res.status_code == 200
    assert any(p["media_id"] == "MID" for p in res.json())

    res = api_client.post(f"/api/publications/{log.id}/refresh-stats")
    assert res.status_code == 200, res.text
    assert res.json()["view_count"] == 10
    assert res.json()["like_count"] == 3


def test_video_upload_rejects_unknown_extension(api_client):
    res = api_client.post(
        "/api/videos",
        files={"file": ("x.txt", io.BytesIO(b"abc"), "text/plain")},
    )
    assert res.status_code == 400


def test_video_get_serves_uploaded_file(api_client, app_env):
    payload = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100
    res = api_client.post(
        "/api/videos",
        files={"file": ("serve.mp4", io.BytesIO(payload), "video/mp4")},
    )
    assert res.status_code == 201, res.text
    filename = res.json()["filename"]

    res = api_client.get(f"/api/videos/{filename}")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("video/")
    assert res.content.startswith(b"\x00\x00\x00\x18")


def test_video_get_404_for_missing(api_client):
    res = api_client.get("/api/videos/missing-file.mp4")
    assert res.status_code == 404


def test_video_get_rejects_path_traversal(api_client, app_env):
    app_env.video_source_dir.mkdir(parents=True, exist_ok=True)
    res = api_client.get("/api/videos/..%2Fsecret.mp4")
    assert res.status_code == 404


def test_video_list_includes_duration_when_probe_available(api_client, monkeypatch):
    payload = b"\x00" * 64
    res = api_client.post(
        "/api/videos",
        files={"file": ("dur.mp4", io.BytesIO(payload), "video/mp4")},
    )
    assert res.status_code == 201

    class _Meta:
        duration_sec = 12.5

    monkeypatch.setattr("app.video.uniquifier.probe", lambda path: _Meta())
    res = api_client.get("/api/videos")
    row = next(v for v in res.json() if v["filename"] == "dur.mp4")
    assert row["duration_sec"] == 12.5


def test_jobs_filter_by_status(api_client):
    res = api_client.get("/api/jobs", params={"status": "queued"})
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_events_endpoint_returns_list(api_client):
    res = api_client.get("/api/events")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_browser_routes_start_status_code_save_stop(api_client, app_env, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from app.browser.session_manager import BrowserSessionStatus, browser_session_manager
    from app.config import settings
    from app.db import Account, Proxy

    monkeypatch.setattr(settings, "browser_vnc_enabled", True, raising=True)

    async def _fake_start(account, proxy, **kwargs):
        browser_session_manager._sessions[account.username] = MagicMock(
            username=account.username,
            status=BrowserSessionStatus.running,
            awaiting_code=False,
            ws_port=16080,
            vnc_path=f"/api/accounts/{account.username}/browser/vnc/ws",
            page_url="https://www.instagram.com/",
            error=None,
        )
        return browser_session_manager._sessions[account.username]

    monkeypatch.setattr(browser_session_manager, "start_session", _fake_start)
    monkeypatch.setattr(
        browser_session_manager,
        "status_dict",
        lambda username: {
            "username": username,
            "status": "running",
            "awaiting_code": False,
            "vnc_path": f"/api/accounts/{username}/browser/vnc/ws",
            "page_url": "https://www.instagram.com/",
            "error": None,
            "login_surface": "mobile",
        },
    )
    monkeypatch.setattr(browser_session_manager, "submit_code", AsyncMock(return_value=True))

    async def _fake_save(db, account):
        account.session_id = "s" * 40
        db.commit()
        return {"session_imported": True, "session_id_saved": True}

    monkeypatch.setattr(browser_session_manager, "save_session", _fake_save)
    monkeypatch.setattr(browser_session_manager, "stop_session", AsyncMock())

    called = {"n": 0}

    def _connection_ok(acc, db):
        called["n"] += 1
        from datetime import datetime, timezone

        from app.api.schemas import (
            AccountConnectionTestOut,
            InstagramAuthStepOut,
            ProxyHealthStepOut,
            SessionStorageStepOut,
        )

        username = acc.username
        return AccountConnectionTestOut(
            username=username,
            proxy_assigned=True,
            proxy_label="br-proxy",
            proxy_health=ProxyHealthStepOut(ok=True, instagram_reachable=True),
            session_storage=SessionStorageStepOut(
                has_session_id=True,
                session_file_exists=False,
                device_file_exists=True,
                session_source="database",
            ),
            instagram_auth=InstagramAuthStepOut(ok=True, method="sessionid", challenge=False),
            overall_ok=True,
            checked_at=datetime.now(timezone.utc),
            run_id=1,
            logs=[],
        )

    monkeypatch.setattr(
        "app.accounts.connection_test.run_account_connection_test",
        _connection_ok,
    )

    db = app_env.SessionLocal()
    proxy = Proxy(label="br-proxy", url="http://u:p@1.2.3.4:8080", country="US")
    db.add(proxy)
    db.commit()
    account = Account(username="browser_user", password="secret", proxy_id=proxy.id)
    db.add(account)
    db.commit()

    start = api_client.post("/api/accounts/browser_user/browser/start?login_surface=mobile")
    assert start.status_code == 200
    assert start.json()["status"] == "running"
    assert start.json()["login_surface"] == "mobile"
    assert start.json()["account_username"] == "browser_user"
    assert start.json()["account_login"] == "browser_user"
    assert start.json()["account_password"] == "secret"
    assert start.json()["account_notes"] is None

    status = api_client.get("/api/accounts/browser_user/browser/status")
    assert status.status_code == 200
    assert status.json()["account_password"] == "secret"

    code = api_client.post("/api/accounts/browser_user/browser/code", json={"code": "123456"})
    assert code.status_code == 200

    save = api_client.post("/api/accounts/browser_user/browser/save")
    assert save.status_code == 200
    body = save.json()
    assert body["session_imported"] is True
    assert body["overall_ok"] is True
    assert body["connection_test"] is None
    assert called["n"] == 0
    assert any("Mobile API-проверка пропущена" in line["message"] for line in body["logs"])

    stop = api_client.delete("/api/accounts/browser_user/browser/stop")
    assert stop.status_code == 200
