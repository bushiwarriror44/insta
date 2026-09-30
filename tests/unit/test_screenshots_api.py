"""Signed screenshot delivery rejects bad tickets."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def api_client(app_env, monkeypatch):
    from app.api import deps as api_deps
    from app.api.main import create_app
    from app.config import settings

    monkeypatch.setattr(settings, "admin_token", "", raising=True)

    app = create_app()

    def _override_get_db():
        db = app_env.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[api_deps.get_db] = _override_get_db
    return TestClient(app)


def test_screenshot_serve_rejects_bad_signature(api_client: TestClient):
    expires = int(time.time()) + 3600
    res = api_client.get(
        "/api/screenshots/evil.png",
        params={"expires": expires, "sig": "deadbeef"},
    )
    assert res.status_code == 403
