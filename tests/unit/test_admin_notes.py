"""Owner/open-mode Administration notebook."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def auth_client(app_env, monkeypatch):
    from app.api import deps as api_deps
    from app.api.main import create_app
    from app.config import settings

    monkeypatch.setattr(settings, "admin_token", "secret-token", raising=True)
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
def open_client(app_env, monkeypatch):
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


def _h():
    return {"Authorization": "Bearer secret-token"}


def test_get_empty_notes_open_mode(open_client):
    res = open_client.get("/api/admin-notes")
    assert res.status_code == 200
    body = res.json()
    assert body["content"] == ""
    assert "updated_at" in body


def test_put_then_get_persists(open_client):
    put = open_client.put("/api/admin-notes", json={"content": "Salad org acme"})
    assert put.status_code == 200
    assert put.json()["content"] == "Salad org acme"
    got = open_client.get("/api/admin-notes")
    assert got.status_code == 200
    assert got.json()["content"] == "Salad org acme"


def test_operator_forbidden(auth_client):
    created = auth_client.post(
        "/api/operators",
        headers=_h(),
        json={"label": "ops-notes"},
    )
    assert created.status_code == 201
    op_headers = {"Authorization": f"Bearer {created.json()['password']}"}
    assert auth_client.get("/api/admin-notes", headers=op_headers).status_code == 403
    assert (
        auth_client.put(
            "/api/admin-notes",
            headers=op_headers,
            json={"content": "nope"},
        ).status_code
        == 403
    )


def test_owner_can_write(auth_client):
    res = auth_client.put(
        "/api/admin-notes",
        headers=_h(),
        json={"content": "host salad.cloud"},
    )
    assert res.status_code == 200
    assert res.json()["content"] == "host salad.cloud"


def test_too_long_rejected(open_client):
    res = open_client.put("/api/admin-notes", json={"content": "x" * 200_001})
    assert res.status_code == 422
