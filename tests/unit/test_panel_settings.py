"""Tests for panel gate and owner settings."""
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


def test_gate_open_mode_allows_any_path(open_client):
    res = open_client.get("/api/panel/gate", params={"path": "/"})
    assert res.status_code == 200
    body = res.json()
    assert body["allowed"] is True
    assert body["entry_path"] is None


def test_gate_wrong_path_denied(auth_client, app_env):
    from app.panel.settings_store import get_or_create_panel_settings

    with app_env.SessionLocal() as db:
        row = get_or_create_panel_settings(db)
        entry = row.entry_path

    bad = auth_client.get("/api/panel/gate", params={"path": "/"})
    assert bad.status_code == 200
    assert bad.json()["allowed"] is False
    assert bad.json()["entry_path"] is None

    ok = auth_client.get("/api/panel/gate", params={"path": entry})
    assert ok.json()["allowed"] is True
    assert ok.json()["entry_path"] == entry

    nested = auth_client.get("/api/panel/gate", params={"path": f"{entry}/accounts"})
    assert nested.json()["allowed"] is True


def test_settings_owner_only(auth_client):
    created = auth_client.post(
        "/api/operators",
        headers=_h(),
        json={"label": "ops-set"},
    ).json()
    op_headers = {"Authorization": f"Bearer {created['password']}"}

    assert auth_client.get("/api/settings", headers=op_headers).status_code == 403
    assert auth_client.get("/api/settings", headers=_h()).status_code == 200


def test_openapi_owner_only(auth_client):
    created = auth_client.post(
        "/api/operators",
        headers=_h(),
        json={"label": "ops-docs"},
    )
    assert created.status_code == 201
    op_headers = {"Authorization": f"Bearer {created.json()['password']}"}

    assert auth_client.get("/api/openapi.json").status_code == 401
    assert auth_client.get("/api/openapi.json", headers=op_headers).status_code == 403
    spec = auth_client.get("/api/openapi.json", headers=_h())
    assert spec.status_code == 200
    assert spec.json().get("openapi")
    assert auth_client.get("/api/docs").status_code == 404


def test_openapi_open_mode(open_client):
    spec = open_client.get("/api/openapi.json")
    assert spec.status_code == 200
    assert spec.json().get("openapi")


def test_update_entry_path(auth_client):
    new_path = "/mySecretPath99"
    res = auth_client.put(
        "/api/settings/entry-path",
        headers=_h(),
        json={"path": new_path, "current_password": "secret-token"},
    )
    assert res.status_code == 200
    assert res.json()["entry_path"] == new_path

    gate = auth_client.get("/api/panel/gate", params={"path": new_path})
    assert gate.json()["allowed"] is True


def test_update_entry_path_rejects_reserved(auth_client):
    res = auth_client.put(
        "/api/settings/entry-path",
        headers=_h(),
        json={"path": "/api/secretpath", "current_password": "secret-token"},
    )
    assert res.status_code == 400


def test_update_entry_path_wrong_password(auth_client):
    before = auth_client.get("/api/settings", headers=_h()).json()["entry_path"]
    res = auth_client.put(
        "/api/settings/entry-path",
        headers=_h(),
        json={"path": "/NewSecretPath1", "current_password": "wrong-password"},
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Неверный текущий пароль"
    after = auth_client.get("/api/settings", headers=_h()).json()["entry_path"]
    assert after == before


def test_master_password_change(auth_client, monkeypatch):
    from app.config import settings

    res = auth_client.put(
        "/api/settings/master-password",
        headers=_h(),
        json={
            "current_password": "secret-token",
            "new_password": "new-master-pw",
        },
    )
    assert res.status_code == 200
    assert res.json()["master_password_set"] is True

    # Env token still works as break-glass
    assert (
        auth_client.get("/api/dashboard", headers=_h()).status_code == 200
    )

    # New password works
    assert (
        auth_client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer new-master-pw"},
        ).status_code
        == 200
    )

    # Clear env token — only DB hash remains
    monkeypatch.setattr(settings, "admin_token", "", raising=True)
    # Re-create app would be needed for settings object... settings is same module
    # auth_is_required checks admin_token OR hash — hash still set
    me = auth_client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer new-master-pw"},
    )
    assert me.status_code == 200
    assert me.json()["role"] == "owner"

    denied = auth_client.get(
        "/api/dashboard",
        headers={"Authorization": "Bearer secret-token"},
    )
    assert denied.status_code == 401
