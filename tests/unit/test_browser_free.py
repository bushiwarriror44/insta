"""Free browser (adhoc VNC) API and profile paths."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.browser.studio_native_chrome import native_chrome_profile_dir


def test_adhoc_profile_dir(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "playwright_dir", tmp_path / "playwright")
    path = native_chrome_profile_dir("adhoc-abc123", "youtube")
    assert path == tmp_path / "playwright" / "adhoc" / "adhoc-abc123" / "chrome_profile"
    assert path.is_dir()


@pytest.fixture()
def auth_client(app_env, monkeypatch):
    from app.api import deps as api_deps
    from app.api.main import create_app
    from app.config import settings
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "admin_token", "secret-token", raising=True)
    monkeypatch.setattr(settings, "browser_vnc_enabled", True, raising=True)
    monkeypatch.setattr(settings, "studio_vnc_native_chrome", True, raising=True)
    app = create_app()

    def _override_get_db():
        db = app_env.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[api_deps.get_db] = _override_get_db
    return TestClient(app)


def _h():
    return {"Authorization": "Bearer secret-token"}


def test_start_requires_proxy(auth_client, app_env):
    res = auth_client.post(
        "/api/browser/free/start",
        headers=_h(),
        json={"proxy_label": "missing-proxy"},
    )
    assert res.status_code == 404


def test_start_returns_adhoc_session(auth_client, app_env, monkeypatch):
    from app.db import Proxy

    db = app_env.SessionLocal()
    try:
        proxy = Proxy(
            label="free-p1",
            url="http://user:pass@127.0.0.1:18080",
            country="US",
            timezone="America/New_York",
        )
        db.add(proxy)
        db.commit()
    finally:
        db.close()

    fake_session = MagicMock()
    fake_session.username = "adhoc-deadbeef1234"

    with patch(
        "app.api.routes.browser_free.browser_session_manager.start_free_session",
        new_callable=AsyncMock,
        return_value=fake_session,
    ):
        res = auth_client.post(
            "/api/browser/free/start",
            headers=_h(),
            json={"proxy_label": "free-p1", "initial_url": "https://example.com"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["username"].startswith("adhoc-")


def test_status_rejects_non_adhoc(auth_client):
    res = auth_client.get("/api/browser/free/alice/status", headers=_h())
    assert res.status_code == 404
