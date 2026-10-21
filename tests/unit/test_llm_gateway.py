"""LLM gateway: dedicated key, OpenAI proxy, MCP handshake."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clear_gateway_activity():
    from app.services.llm_gateway_activity import clear_activity

    clear_activity()
    yield
    clear_activity()


@pytest.fixture()
def auth_client(app_env, monkeypatch):
    from app.api import deps as api_deps
    from app.api.main import create_app
    from app.config import settings

    monkeypatch.setattr(settings, "admin_token", "secret-token", raising=True)
    monkeypatch.setattr(settings, "agent_base_url", "http://ollama.test/v1", raising=True)
    monkeypatch.setattr(settings, "agent_model", "qwen3:8b", raising=True)
    monkeypatch.setattr(settings, "agent_api_key", "", raising=True)
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
    monkeypatch.setattr(settings, "agent_base_url", "http://ollama.test/v1", raising=True)
    monkeypatch.setattr(settings, "agent_model", "qwen3:8b", raising=True)
    app = create_app()

    def _override_get_db():
        db = app_env.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[api_deps.get_db] = _override_get_db
    return TestClient(app)


def _owner():
    return {"Authorization": "Bearer secret-token"}


def test_credentials_create_and_rotate(auth_client, app_env):
    with patch("app.api.routes.llm_gateway.ollama_reachable", return_value=True):
        first = auth_client.get("/api/llm-gateway/credentials", headers=_owner())
    assert first.status_code == 200
    body = first.json()
    assert body["base_url"].endswith("/llm/v1")
    assert body["mcp_url"].endswith("/mcp")
    assert body["api_key"]
    assert body["model"] == "qwen3:8b"
    assert body["upstream_ok"] is True
    assert "reels-salad" in body["mcp_json"]
    key1 = body["api_key"]

    with patch("app.api.routes.llm_gateway.ollama_reachable", return_value=False):
        rotated = auth_client.post("/api/llm-gateway/rotate", headers=_owner())
    assert rotated.status_code == 200
    key2 = rotated.json()["api_key"]
    assert key2 != key1

    with app_env.SessionLocal() as db:
        from app.panel.settings_store import get_or_create_panel_settings

        row = get_or_create_panel_settings(db)
        assert row.llm_gateway_token == key2


def test_credentials_reject_without_auth(auth_client):
    res = auth_client.get("/api/llm-gateway/credentials")
    assert res.status_code == 401


def test_proxy_rejects_admin_token(auth_client):
    with patch("app.api.routes.llm_gateway.ollama_reachable", return_value=True):
        creds = auth_client.get("/api/llm-gateway/credentials", headers=_owner()).json()

    res = auth_client.get(
        "/llm/v1/models",
        headers={"Authorization": "Bearer secret-token"},
    )
    assert res.status_code == 401

    res_ok_key = creds["api_key"]
    mock_response = httpx.Response(
        200,
        json={"data": [{"id": "qwen3:8b"}]},
        request=httpx.Request("GET", "http://ollama.test/v1/models"),
    )
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.request = AsyncMock(return_value=mock_response)

    with patch("app.api.routes.llm_gateway.httpx.AsyncClient", return_value=mock_client):
        ok = auth_client.get(
            "/llm/v1/models",
            headers={"Authorization": f"Bearer {res_ok_key}"},
        )
    assert ok.status_code == 200
    assert ok.json()["data"][0]["id"] == "qwen3:8b"
    called_url = mock_client.request.call_args.args[1]
    assert called_url == "http://ollama.test/v1/models"


def test_proxy_forwards_chat_completions(auth_client):
    with patch("app.api.routes.llm_gateway.ollama_reachable", return_value=True):
        key = auth_client.get("/api/llm-gateway/credentials", headers=_owner()).json()["api_key"]

    mock_response = httpx.Response(
        200,
        json={"choices": [{"message": {"content": "hi"}}]},
        request=httpx.Request("POST", "http://ollama.test/v1/chat/completions"),
    )
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.request = AsyncMock(return_value=mock_response)

    with patch("app.api.routes.llm_gateway.httpx.AsyncClient", return_value=mock_client):
        res = auth_client.post(
            "/llm/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "qwen3:8b", "messages": [{"role": "user", "content": "ping"}]},
        )
    assert res.status_code == 200
    assert res.json()["choices"][0]["message"]["content"] == "hi"
    method, url = mock_client.request.call_args.args[:2]
    assert method == "POST"
    assert url == "http://ollama.test/v1/chat/completions"


def test_mcp_initialize_and_tools_list(auth_client):
    with patch("app.api.routes.llm_gateway.ollama_reachable", return_value=True):
        key = auth_client.get("/api/llm-gateway/credentials", headers=_owner()).json()["api_key"]
    headers = {"Authorization": f"Bearer {key}"}

    init = auth_client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert init.status_code == 200
    assert init.json()["result"]["serverInfo"]["name"] == "reels-salad"

    tools = auth_client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )
    assert tools.status_code == 200
    names = [t["name"] for t in tools.json()["result"]["tools"]]
    assert names == ["chat"]


def test_mcp_chat_tool(auth_client):
    with patch("app.api.routes.llm_gateway.ollama_reachable", return_value=True):
        key = auth_client.get("/api/llm-gateway/credentials", headers=_owner()).json()["api_key"]

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "salad reply"}}]
    }
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_cm
    mock_cm.__exit__.return_value = None
    mock_cm.post.return_value = mock_response

    with patch("app.api.routes.llm_gateway.http_client", return_value=mock_cm):
        res = auth_client.post(
            "/mcp",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "chat", "arguments": {"prompt": "hello"}},
            },
        )
    assert res.status_code == 200
    text = res.json()["result"]["content"][0]["text"]
    assert text == "salad reply"


def test_open_mode_credentials(open_client):
    with patch("app.api.routes.llm_gateway.ollama_reachable", return_value=False):
        res = open_client.get("/api/llm-gateway/credentials")
    assert res.status_code == 200
    assert res.json()["api_key"]
    assert res.json()["enabled"] is True
    assert res.json()["recent"] == []
    assert "mcpServers" in json.loads(res.json()["mcp_json"])


def test_disable_blocks_proxy_and_mcp(auth_client):
    with patch("app.api.routes.llm_gateway.ollama_reachable", return_value=True):
        key = auth_client.get("/api/llm-gateway/credentials", headers=_owner()).json()["api_key"]

    disabled = auth_client.post(
        "/api/llm-gateway/enabled",
        headers=_owner(),
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    blocked = auth_client.get(
        "/llm/v1/models",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert blocked.status_code == 503
    assert "выключен" in blocked.json()["detail"].lower()

    mcp_blocked = auth_client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {key}"},
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
    )
    assert mcp_blocked.status_code == 503

    enabled = auth_client.post(
        "/api/llm-gateway/enabled",
        headers=_owner(),
        json={"enabled": True},
    )
    assert enabled.json()["enabled"] is True

    mock_response = httpx.Response(
        200,
        json={"data": []},
        request=httpx.Request("GET", "http://ollama.test/v1/models"),
    )
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.request = AsyncMock(return_value=mock_response)
    with patch("app.api.routes.llm_gateway.httpx.AsyncClient", return_value=mock_client):
        ok = auth_client.get(
            "/llm/v1/models",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert ok.status_code == 200


def test_rotate_invalidates_old_key(auth_client):
    with patch("app.api.routes.llm_gateway.ollama_reachable", return_value=True):
        old = auth_client.get("/api/llm-gateway/credentials", headers=_owner()).json()["api_key"]
        new = auth_client.post("/api/llm-gateway/rotate", headers=_owner()).json()["api_key"]
    assert old != new
    assert (
        auth_client.get(
            "/llm/v1/models",
            headers={"Authorization": f"Bearer {old}"},
        ).status_code
        == 401
    )


def test_proxy_records_recent_activity(auth_client):
    with patch("app.api.routes.llm_gateway.ollama_reachable", return_value=True):
        key = auth_client.get("/api/llm-gateway/credentials", headers=_owner()).json()["api_key"]

    mock_response = httpx.Response(
        200,
        json={"data": [{"id": "qwen3:8b"}]},
        request=httpx.Request("GET", "http://ollama.test/v1/models"),
    )
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.request = AsyncMock(return_value=mock_response)

    with patch("app.api.routes.llm_gateway.httpx.AsyncClient", return_value=mock_client):
        assert (
            auth_client.get(
                "/llm/v1/models",
                headers={"Authorization": f"Bearer {key}", "User-Agent": "cursor-test"},
            ).status_code
            == 200
        )

    with patch("app.api.routes.llm_gateway.ollama_reachable", return_value=True):
        recent = auth_client.get("/api/llm-gateway/credentials", headers=_owner()).json()["recent"]
    assert recent
    assert recent[0]["channel"] == "llm"
    assert recent[0]["path"].endswith("/models")
    assert recent[0]["status"] == 200
    assert recent[0]["user_agent"] == "cursor-test"
