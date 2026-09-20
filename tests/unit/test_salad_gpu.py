"""Salad GPU Start/Stop from the admin panel."""
from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.services.salad_gpu import SALAD_API_ROOT

SECRET = "salad-secret-key-do-not-leak"
GROUP_URL = f"{SALAD_API_ROOT}/organizations/acme/projects/gpu/containers/insta-gpu"


@pytest.fixture()
def auth_client(app_env, monkeypatch):
    from app.api import deps as api_deps
    from app.api.main import create_app
    from app.config import settings

    monkeypatch.setattr(settings, "admin_token", "secret-token", raising=True)
    monkeypatch.setattr(settings, "agent_base_url", "", raising=True)
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
    monkeypatch.setattr(settings, "agent_base_url", "", raising=True)
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


def _configure(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "salad_api_key", SECRET, raising=True)
    monkeypatch.setattr(settings, "salad_organization", "acme", raising=True)
    monkeypatch.setattr(settings, "salad_project", "gpu", raising=True)
    monkeypatch.setattr(settings, "salad_container_group", "insta-gpu", raising=True)


def _state(
    status: str,
    *,
    running: int = 0,
    creating: int = 0,
    allocating: int = 0,
    stopping: int = 0,
) -> dict:
    return {
        "current_state": {
            "status": status,
            "start_time": "2026-01-01T00:00:00Z",
            "finish_time": "2026-01-01T00:00:00Z",
            "instance_status_counts": {
                "allocating_count": allocating,
                "creating_count": creating,
                "running_count": running,
                "stopping_count": stopping,
            },
        }
    }


def test_get_unconfigured_does_not_call_salad(auth_client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "salad_api_key", "", raising=True)
    with respx.mock:
        res = auth_client.get("/api/gpu", headers=_h())
    assert res.status_code == 200
    body = res.json()
    assert body["configured"] is False
    assert body["status"] is None
    assert body["billing"] is False
    assert SECRET not in res.text
    assert "Salad-Api-Key" not in res.text


def test_get_open_mode_unconfigured(open_client):
    res = open_client.get("/api/gpu")
    assert res.status_code == 200
    assert res.json()["configured"] is False


def test_operator_forbidden(auth_client):
    created = auth_client.post(
        "/api/operators",
        headers=_h(),
        json={"label": "ops-gpu"},
    )
    assert created.status_code == 201
    op_headers = {"Authorization": f"Bearer {created.json()['password']}"}
    assert auth_client.get("/api/gpu", headers=op_headers).status_code == 403
    assert auth_client.post("/api/gpu/start", headers=op_headers).status_code == 403
    assert auth_client.post("/api/gpu/stop", headers=op_headers).status_code == 403


def test_start_unconfigured_is_503(auth_client):
    res = auth_client.post("/api/gpu/start", headers=_h())
    assert res.status_code == 503
    assert "SALAD_API_KEY" in res.json()["detail"]
    assert SECRET not in res.text


@respx.mock
def test_chat_ok_without_putting_the_url_in_the_body(auth_client, monkeypatch):
    _configure(monkeypatch)
    from app.config import settings

    monkeypatch.setattr(settings, "agent_base_url", "https://gpu.example/v1", raising=True)
    respx.get(GROUP_URL).mock(
        return_value=httpx.Response(200, json=_state("running", running=1))
    )
    respx.get("https://gpu.example/api/tags").mock(
        return_value=httpx.Response(200, json={"models": []})
    )
    res = auth_client.get("/api/gpu", headers=_h())
    assert res.status_code == 200
    assert res.json()["chat_ok"] is True
    assert "gpu.example" not in res.text
    assert SECRET not in res.text


@respx.mock
def test_get_running_and_key_stays_off_the_wire_body(auth_client, monkeypatch):
    _configure(monkeypatch)
    respx.get(GROUP_URL).mock(
        return_value=httpx.Response(200, json=_state("running", running=1))
    )
    res = auth_client.get("/api/gpu", headers=_h())
    assert res.status_code == 200
    body = res.json()
    assert body["configured"] is True
    assert body["status"] == "running"
    assert body["billing"] is True
    assert body["running_count"] == 1
    assert body["chat_ok"] is False
    assert SECRET not in res.text
    assert SECRET == respx.calls[0].request.headers["salad-api-key"]


@respx.mock
def test_start_posts_start_then_reads_status(auth_client, monkeypatch):
    _configure(monkeypatch)
    respx.get(GROUP_URL).mock(
        side_effect=[
            httpx.Response(200, json=_state("stopped")),
            httpx.Response(200, json=_state("deploying", creating=1)),
        ]
    )
    start = respx.post(f"{GROUP_URL}/start").mock(return_value=httpx.Response(202))
    res = auth_client.post("/api/gpu/start", headers=_h())
    assert res.status_code == 200
    assert start.called
    assert start.calls[0].request.method == "POST"
    assert start.calls[0].request.headers["salad-api-key"] == SECRET
    body = res.json()
    assert body["status"] == "deploying"
    assert body["billing"] is False
    assert body["creating_count"] == 1
    assert SECRET not in res.text


@respx.mock
def test_start_conflict_when_already_running(auth_client, monkeypatch):
    _configure(monkeypatch)
    respx.get(GROUP_URL).mock(
        return_value=httpx.Response(200, json=_state("running", running=1))
    )
    start = respx.post(f"{GROUP_URL}/start").mock(return_value=httpx.Response(202))
    res = auth_client.post("/api/gpu/start", headers=_h())
    assert res.status_code == 409
    assert start.called is False
    assert SECRET not in res.text


@respx.mock
def test_stop_posts_stop(auth_client, monkeypatch):
    _configure(monkeypatch)
    respx.get(GROUP_URL).mock(
        side_effect=[
            httpx.Response(200, json=_state("running", running=1)),
            httpx.Response(200, json=_state("stopped")),
        ]
    )
    stop = respx.post(f"{GROUP_URL}/stop").mock(return_value=httpx.Response(202))
    res = auth_client.post("/api/gpu/stop", headers=_h())
    assert res.status_code == 200
    assert stop.called
    assert res.json()["status"] == "stopped"
    assert res.json()["billing"] is False
    assert SECRET not in res.text


@respx.mock
def test_stop_conflict_when_already_stopped(auth_client, monkeypatch):
    _configure(monkeypatch)
    respx.get(GROUP_URL).mock(
        return_value=httpx.Response(200, json=_state("stopped"))
    )
    stop = respx.post(f"{GROUP_URL}/stop").mock(return_value=httpx.Response(202))
    res = auth_client.post("/api/gpu/stop", headers=_h())
    assert res.status_code == 409
    assert stop.called is False


@respx.mock
def test_salad_403_does_not_echo_key(auth_client, monkeypatch):
    _configure(monkeypatch)
    respx.get(GROUP_URL).mock(
        return_value=httpx.Response(403, json={"message": "nope", "key": SECRET})
    )
    res = auth_client.get("/api/gpu", headers=_h())
    assert res.status_code == 403
    assert res.json()["detail"] == "Salad отказал в доступе"
    assert SECRET not in res.text
