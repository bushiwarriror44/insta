"""Floppydata generate + import into panel proxy pool."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def auth_client(app_env, monkeypatch):
    from app.api import deps as api_deps
    from app.api.main import create_app
    from app.config import settings

    monkeypatch.setattr(settings, "admin_token", "secret-token", raising=True)
    monkeypatch.setattr(settings, "floppydata_api_key", "fd-test-key", raising=True)
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
def no_key_client(app_env, monkeypatch):
    from app.api import deps as api_deps
    from app.api.main import create_app
    from app.config import settings

    monkeypatch.setattr(settings, "admin_token", "secret-token", raising=True)
    monkeypatch.setattr(settings, "floppydata_api_key", "", raising=True)
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


def test_status_without_key(no_key_client):
    res = no_key_client.get("/api/floppydata/status", headers=_h())
    assert res.status_code == 200
    assert res.json()["configured"] is False


def test_status_normalizes_nested_balance(auth_client):
    nested = {
        "expiring": {
            "expiresAt": "2026-01-25T08:33:30Z",
            "traffic": {"availableBytes": 10737418240, "availableGb": 10},
        },
        "nonExpiring": {
            "traffic": {"availableBytes": 5368709120, "availableGb": 5},
        },
        "total": {
            "traffic": {"availableBytes": 16106127360, "availableGb": 15},
        },
    }
    with patch("app.services.floppydata.rotating_balance", return_value=nested):
        res = auth_client.get("/api/floppydata/status", headers=_h())
    assert res.status_code == 200
    body = res.json()
    assert body["configured"] is True
    assert body["balance_gb"] == 15
    assert body["balance_bytes"] == 16106127360
    assert body["expiring_gb"] == 10
    assert body["expiring_at"] == "2026-01-25T08:33:30Z"
    assert "balance" not in body or body.get("balance") is None


def test_generate_requires_key(no_key_client):
    res = no_key_client.post(
        "/api/floppydata/generate",
        headers=_h(),
        json={
            "type": "residential",
            "country": "US",
            "protocol": "http",
            "rotation": 0,
            "count": 1,
        },
    )
    assert res.status_code == 400
    assert "ключ" in res.json()["detail"].lower()


def test_generate_calls_n_times(auth_client):
    calls = {"n": 0}

    def fake_build(_key, body):
        calls["n"] += 1
        return {
            "connection": {
                "protocol": "http",
                "host": "geo.g-w.info",
                "port": 10080,
                "username": f"user-{calls['n']}",
                "password": "pw",
                "connectionString": f"http://user-{calls['n']}:pw@geo.g-w.info:10080",
            },
            "parameters": body,
        }

    with patch("app.services.floppydata.build_connection", side_effect=fake_build):
        res = auth_client.post(
            "/api/floppydata/generate",
            headers=_h(),
            json={
                "type": "mobile",
                "country": "AM",
                "protocol": "http",
                "rotation": 0,
                "count": 3,
            },
        )
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 3
    assert calls["n"] == 3
    assert items[0]["connection_string"].startswith("http://")

    status = auth_client.get("/api/floppydata/status", headers=_h())
    assert status.status_code == 200
    assert status.json()["last_form"]["type"] == "mobile"
    assert status.json()["last_form"]["country"] == "AM"
    assert status.json()["last_form"]["count"] == 3


def test_import_creates_proxies(auth_client, app_env, monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.floppydata.health_check_record",
        lambda db, proxy: (True, None, None),
    )
    res = auth_client.post(
        "/api/floppydata/import",
        headers=_h(),
        json={
            "run_health_check": True,
            "form": {
                "type": "residential",
                "country": "US",
                "protocol": "http",
                "rotation": 0,
                "count": 1,
            },
            "items": [
                {
                    "label": "floppy-am-1",
                    "url": "http://u:p@geo.g-w.info:10080",
                    "country": "AM",
                }
            ],
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["label"] == "floppy-am-1"
    assert body[0]["url"].startswith("http://")
    assert body[0].get("created_at")

    with app_env.SessionLocal() as db:
        from app.db import Proxy
        from app.panel.settings_store import get_floppydata_last_form

        row = db.query(Proxy).filter(Proxy.label == "floppy-am-1").one()
        assert row.notes == "floppydata"
        form = get_floppydata_last_form(db)
        assert form is not None
        assert form["country"] == "US"
        assert form["type"] == "residential"
