"""Block 0: smoke that documented API routers exist and key endpoints respond."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.assistant import tools as assistant_tools


@pytest.fixture()
def open_client(app_env, monkeypatch):
    from app.api import deps as api_deps
    from app.api.main import create_app
    from app.config import settings

    monkeypatch.setattr(settings, "admin_token", "", raising=True)
    monkeypatch.setattr("app.proxies.pool.health_check", lambda *a, **kw: {"ip": "203.0.113.5"})

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
    from app.api import deps as api_deps
    from app.api.main import create_app
    from app.config import settings

    monkeypatch.setattr(settings, "admin_token", "secret-token", raising=True)
    monkeypatch.setattr("app.proxies.pool.health_check", lambda *a, **kw: {"ip": "203.0.113.5"})

    app = create_app()

    def _override_get_db():
        db = app_env.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[api_deps.get_db] = _override_get_db
    return TestClient(app, headers={"Authorization": "Bearer secret-token"})


def test_create_app_registers_core_routers(open_client):
    paths = {route.path for route in open_client.app.routes if hasattr(route, "path")}
    assert "/api/health" in paths
    assert "/api/events" in paths
    assert any(p.startswith("/api/maintenance") for p in paths)


def test_health_open(open_client):
    res = open_client.get("/api/health")
    assert res.status_code == 200


def test_events_list_auth(auth_client):
    res = auth_client.get("/api/events")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_maintenance_runtime_auth(auth_client, monkeypatch):
    class _RuntimeStub:
        reachable = False
        base_url = ""
        models = []
        loaded = []
        detail = "mock"

        def context_of(self, _model: str) -> None:
            return None

    monkeypatch.setattr(
        "app.api.routes.maintenance.runtime.probe",
        lambda _settings=None: _RuntimeStub(),
    )
    res = auth_client.get("/api/maintenance/runtime")
    assert res.status_code == 200
    assert "reachable" in res.json()


def test_docker_logs_whitelist_matches_compose():
    """Assistant docker_logs service names align with docker-compose.yml."""
    expected = {
        "reels-api",
        "reels-worker",
        "reels-frontend",
        "reels-ollama",
        "reels-ollama-pull",
    }
    assert assistant_tools.COMPOSE_SERVICES == expected


def test_docker_logs_rejects_unknown_service():
    from app.assistant.tools import ToolError, docker_logs

    with pytest.raises(ToolError, match="reels-api"):
        docker_logs("unknown-service")
