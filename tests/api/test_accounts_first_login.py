"""API tests for account first-login endpoint."""

import pytest
from fastapi.testclient import TestClient

from app.api.schemas import FirstLoginOut


@pytest.fixture()
def api_client(app_env, monkeypatch):
    from app.api import deps as api_deps
    from app.api.main import create_app
    from app.config import settings

    monkeypatch.setattr(settings, "admin_token", "", raising=True)
    monkeypatch.setattr("app.proxies.pool.health_check", lambda *a, **kw: {"ip": "1.2.3.4"})
    monkeypatch.setattr(
        "app.api.routes.accounts.ensure_fingerprint_and_proxy",
        lambda username, country="US": object(),
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


def test_first_login_endpoint_404(api_client):
    res = api_client.post("/api/accounts/nobody/first-login")
    assert res.status_code == 404


def test_first_login_endpoint_503_without_browser(api_client, monkeypatch):
    api_client.post(
        "/api/proxies",
        json={"label": "px-fl-api", "url": "http://u:p@h:1", "skip_health_check": True},
    )
    api_client.post(
        "/api/accounts",
        json={"username": "flapi", "password": "secret", "proxy_label": "px-fl-api"},
    )
    monkeypatch.setattr(
        "app.behavior.warmup_playwright.playwright_browsers_available",
        lambda: False,
    )
    res = api_client.post("/api/accounts/flapi/first-login")
    assert res.status_code == 503


def test_first_login_endpoint_ok(api_client, monkeypatch):
    api_client.post(
        "/api/proxies",
        json={"label": "px-fl2", "url": "http://u:p@h:2", "skip_health_check": True},
    )
    api_client.post(
        "/api/accounts",
        json={"username": "flapi2", "password": "secret", "proxy_label": "px-fl2"},
    )
    monkeypatch.setattr(
        "app.behavior.warmup_playwright.playwright_browsers_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.api.routes.accounts.run_account_first_login",
        lambda account, db, surface=None: FirstLoginOut(
            run_id=1,
            ok=True,
            session_imported=True,
            logs=[],
        ),
    )
    res = api_client.post("/api/accounts/flapi2/first-login?login_surface=desktop")
    assert res.status_code == 200
    assert res.json()["ok"] is True
