"""Tests for panel operators (sub-admin) API and auth."""
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


def _owner_headers():
    return {"Authorization": "Bearer secret-token"}


def test_auth_me_owner(auth_client):
    res = auth_client.get("/api/auth/me", headers=_owner_headers())
    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "owner"
    assert body["label"] == "master"


def test_create_operator_returns_password_once(auth_client):
    res = auth_client.post(
        "/api/operators",
        headers=_owner_headers(),
        json={"label": "ivan"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["label"] == "ivan"
    assert body["active"] is True
    assert body["password"]
    password = body["password"]

    listed = auth_client.get("/api/operators", headers=_owner_headers())
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert "password" not in rows[0]
    assert rows[0]["label"] == "ivan"

    # Operator can use the password as Bearer
    me = auth_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {password}"},
    )
    assert me.status_code == 200
    assert me.json()["role"] == "operator"
    assert me.json()["label"] == "ivan"

    dash = auth_client.get(
        "/api/dashboard",
        headers={"Authorization": f"Bearer {password}"},
    )
    assert dash.status_code == 200


def test_operator_cannot_restore_database_backup(auth_client, monkeypatch, tmp_path):
    import sqlite3

    from app.config import settings

    live = tmp_path / "panel.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{live}", raising=True)
    monkeypatch.setattr(settings, "backup_dir", tmp_path / "backups", raising=True)

    with sqlite3.connect(live) as conn:
        conn.execute("CREATE TABLE restore_guard (v INTEGER)")
        conn.execute("INSERT INTO restore_guard VALUES (1)")
        conn.commit()

    created = auth_client.post("/api/maintenance/backups", headers=_owner_headers())
    assert created.status_code == 200
    name = created.json()["name"]

    op = auth_client.post(
        "/api/operators",
        headers=_owner_headers(),
        json={"label": "no-restore"},
    ).json()
    op_headers = {"Authorization": f"Bearer {op['password']}"}

    denied = auth_client.post(
        "/api/maintenance/backups/restore",
        headers=op_headers,
        json={"name": name},
    )
    assert denied.status_code == 403

    allowed = auth_client.post(
        "/api/maintenance/backups/restore",
        headers=_owner_headers(),
        json={"name": name},
    )
    assert allowed.status_code == 200


def test_operator_cannot_manage_operators(auth_client):
    created = auth_client.post(
        "/api/operators",
        headers=_owner_headers(),
        json={"label": "ops1"},
    ).json()
    password = created["password"]
    headers = {"Authorization": f"Bearer {password}"}

    assert auth_client.get("/api/operators", headers=headers).status_code == 403
    assert (
        auth_client.post("/api/operators", headers=headers, json={"label": "x"}).status_code
        == 403
    )


def test_duplicate_label_conflict(auth_client):
    auth_client.post(
        "/api/operators",
        headers=_owner_headers(),
        json={"label": "dup"},
    )
    res = auth_client.post(
        "/api/operators",
        headers=_owner_headers(),
        json={"label": "dup"},
    )
    assert res.status_code == 409


def test_revoke_blocks_old_password(auth_client):
    created = auth_client.post(
        "/api/operators",
        headers=_owner_headers(),
        json={"label": "temp"},
    ).json()
    password = created["password"]
    op_id = created["id"]

    rev = auth_client.post(
        f"/api/operators/{op_id}/revoke",
        headers=_owner_headers(),
    )
    assert rev.status_code == 200
    assert rev.json()["active"] is False
    assert rev.json()["revoked_at"] is not None

    # Idempotent
    rev2 = auth_client.post(
        f"/api/operators/{op_id}/revoke",
        headers=_owner_headers(),
    )
    assert rev2.status_code == 200

    denied = auth_client.get(
        "/api/dashboard",
        headers={"Authorization": f"Bearer {password}"},
    )
    assert denied.status_code == 401


def test_master_compare_digest_still_works(auth_client):
    ok = auth_client.get("/api/dashboard", headers=_owner_headers())
    assert ok.status_code == 200
    bad = auth_client.get(
        "/api/dashboard",
        headers={"Authorization": "Bearer secret-tokenx"},
    )
    assert bad.status_code == 401


def test_operators_forbidden_in_open_mode(app_env, monkeypatch):
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
    client = TestClient(app)
    assert client.get("/api/operators").status_code == 403
