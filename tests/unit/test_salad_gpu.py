"""Salad GPU Start/Stop from the admin panel."""
from __future__ import annotations

import json

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
    monkeypatch.setattr(settings, "wan_base_url", "", raising=True)


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
    monkeypatch.setattr(settings, "wan_base_url", "", raising=True)
    with respx.mock:
        res = auth_client.get("/api/gpu", headers=_h())
    assert res.status_code == 200
    body = res.json()
    assert body["configured"] is False
    assert body["status"] is None
    assert body["billing"] is False
    assert SECRET not in res.text
    assert "Salad-Api-Key" not in res.text


def test_get_open_mode_unconfigured(open_client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "wan_base_url", "", raising=True)
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
    assert auth_client.get("/api/gpu/logs", headers=op_headers).status_code == 403
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
    assert res.json()["wan_ok"] is None
    assert "gpu.example" not in res.text
    assert SECRET not in res.text


@respx.mock
def test_wan_ok_when_the_host_answers(auth_client, monkeypatch):
    _configure(monkeypatch)
    from app.config import settings

    monkeypatch.setattr(settings, "wan_base_url", "https://wan.example/generate", raising=True)
    respx.get(GROUP_URL).mock(return_value=httpx.Response(200, json=_state("running", running=1)))
    respx.get("https://wan.example/generate").mock(return_value=httpx.Response(200, text="ok"))
    res = auth_client.get("/api/gpu", headers=_h())
    assert res.status_code == 200
    assert res.json()["wan_ok"] is True
    assert "wan.example" not in res.text


@respx.mock
def test_wan_ok_is_false_when_the_host_is_down(auth_client, monkeypatch):
    _configure(monkeypatch)
    from app.config import settings

    monkeypatch.setattr(settings, "wan_base_url", "https://wan.example/generate", raising=True)
    respx.get(GROUP_URL).mock(return_value=httpx.Response(200, json=_state("stopped")))
    respx.get("https://wan.example/generate").mock(side_effect=httpx.ConnectError("down"))
    res = auth_client.get("/api/gpu", headers=_h())
    assert res.status_code == 200
    assert res.json()["wan_ok"] is False
    assert "wan.example" not in res.text
    assert "down" not in res.text


@respx.mock
def test_wan_ok_false_on_404_edge(auth_client, monkeypatch):
    _configure(monkeypatch)
    from app.config import settings

    monkeypatch.setattr(settings, "wan_base_url", "https://wan.example/generate", raising=True)
    respx.get(GROUP_URL).mock(return_value=httpx.Response(200, json=_state("running", running=1)))
    respx.get("https://wan.example/generate").mock(return_value=httpx.Response(404, text="missing"))
    res = auth_client.get("/api/gpu", headers=_h())
    assert res.status_code == 200
    assert res.json()["wan_ok"] is False


@respx.mock
def test_wan_ok_true_on_405_post_only(auth_client, monkeypatch):
    _configure(monkeypatch)
    from app.config import settings

    monkeypatch.setattr(settings, "wan_base_url", "https://wan.example/generate", raising=True)
    respx.get(GROUP_URL).mock(return_value=httpx.Response(200, json=_state("running", running=1)))
    respx.get("https://wan.example/generate").mock(return_value=httpx.Response(405, text="method"))
    res = auth_client.get("/api/gpu", headers=_h())
    assert res.status_code == 200
    assert res.json()["wan_ok"] is True


@respx.mock
def test_stopped_forces_probes_false(auth_client, monkeypatch):
    _configure(monkeypatch)
    from app.config import settings

    monkeypatch.setattr(settings, "agent_base_url", "https://gpu.example/v1", raising=True)
    monkeypatch.setattr(settings, "wan_base_url", "https://wan.example/generate", raising=True)
    respx.get(GROUP_URL).mock(return_value=httpx.Response(200, json=_state("stopped")))
    respx.get("https://gpu.example/api/tags").mock(
        return_value=httpx.Response(200, json={"models": []})
    )
    respx.get("https://wan.example/generate").mock(return_value=httpx.Response(405, text="method"))
    res = auth_client.get("/api/gpu", headers=_h())
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "stopped"
    assert body["chat_ok"] is False
    assert body["wan_ok"] is False


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
def test_salad_403_returns_probes_without_echoing_key(auth_client, monkeypatch):
    _configure(monkeypatch)
    from app.config import settings

    monkeypatch.setattr(settings, "wan_base_url", "https://wan.example/generate", raising=True)
    respx.get(GROUP_URL).mock(
        return_value=httpx.Response(403, json={"message": "nope", "key": SECRET})
    )
    respx.get("https://wan.example/generate").mock(return_value=httpx.Response(404, text="gone"))
    res = auth_client.get("/api/gpu", headers=_h())
    assert res.status_code == 200
    body = res.json()
    assert body["configured"] is True
    assert body["status"] is None
    assert body["detail"] == "Salad отказал в доступе"
    assert body["wan_ok"] is False
    assert SECRET not in res.text
    assert "wan.example" not in res.text


def test_gpu_logs_include_docker_and_salad_without_the_key(auth_client, monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(
        "app.assistant.tools.docker_logs",
        lambda service, tail=80: {
            "available": True,
            "lines": [f"{service} ok"],
            "reason": "",
        },
    )
    with respx.mock:
        route = respx.post(url__regex=r".*/log-entries$").mock(
            return_value=httpx.Response(
                200,
                json={"items": [{"text_log": "ollama ready"}, {"text_log": f"leak {SECRET}"}]},
            )
        )
        res = auth_client.get("/api/gpu/logs", headers=_h())
    assert res.status_code == 200
    body = res.json()
    assert [row["name"] for row in body["docker"]] == [
        "reels-api",
        "reels-worker",
        "reels-frontend",
    ]
    assert body["docker"][0]["lines"] == ["reels-api ok"]
    assert body["gpu"]["available"] is True
    assert body["gpu"]["lines"] == ["leak …", "ollama ready"]
    assert SECRET not in res.text
    sent = json.loads(route.calls[0].request.read().decode())
    assert 'resource.type = "container"' in sent["query"]
    assert "insta-gpu" in sent["query"]
    assert SECRET not in sent["query"]


def test_get_group_turns_a_cut_body_into_salad_problem(monkeypatch):
    from app.services import salad_gpu
    from app.services.salad_gpu import SaladProblem

    _configure(monkeypatch)

    class CutBody:
        status_code = 200

        def json(self):
            raise httpx.RemoteProtocolError("Error in input stream")

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, *args, **kwargs):
            return CutBody()

    monkeypatch.setattr(salad_gpu, "http_client", lambda *a, **k: Client())
    with pytest.raises(SaladProblem, match="не отвечает"):
        salad_gpu.get_group()


def test_gpu_logs_keep_docker_when_salad_is_not_configured(auth_client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "salad_api_key", "", raising=True)
    monkeypatch.setattr(
        "app.assistant.tools.docker_logs",
        lambda service, tail=80: {"available": False, "lines": [], "reason": f"нет {service}"},
    )
    with respx.mock:
        route = respx.post(url__regex=r".*/log-entries$").mock(
            return_value=httpx.Response(500, json={"message": "no"})
        )
        res = auth_client.get("/api/gpu/logs", headers=_h())
    assert res.status_code == 200
    body = res.json()
    assert body["docker"][0]["reason"] == "нет reels-api"
    assert body["gpu"]["available"] is False
    assert body["gpu"]["reason"] == "Salad не настроен"
    assert route.called is False
    assert SECRET not in res.text
