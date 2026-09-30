"""Block 1: browser API must not leak account passwords to operators."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def auth_client(app_env, monkeypatch, make_account):
    from app.api import deps as api_deps
    from app.api.main import create_app
    from app.config import settings

    monkeypatch.setattr(settings, "admin_token", "secret-token", raising=True)
    monkeypatch.setattr("app.proxies.pool.health_check", lambda *a, **kw: {"ip": "203.0.113.5"})
    make_account(username="alice", password="ig-secret-pass")

    app = create_app()

    def _override_get_db():
        db = app_env.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[api_deps.get_db] = _override_get_db
    return TestClient(app)


def test_owner_browser_status_includes_password(auth_client):
    res = auth_client.get(
        "/api/accounts/alice/browser/status",
        headers={"Authorization": "Bearer secret-token"},
    )
    assert res.status_code == 200
    assert res.json().get("account_password") == "ig-secret-pass"


def test_operator_browser_status_hides_password(auth_client):
    created = auth_client.post(
        "/api/operators",
        headers={"Authorization": "Bearer secret-token"},
        json={"label": "browser-op"},
    ).json()
    res = auth_client.get(
        "/api/accounts/alice/browser/status",
        headers={"Authorization": f"Bearer {created['password']}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body.get("account_password") in (None, "")
    assert body.get("account_login") in (None, "")
