"""Human-readable errors for LLM gateway and account proxies."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient


def test_explain_llm_timeout():
    from app.services.llm_gateway_errors import explain_llm_upstream_error

    msg = explain_llm_upstream_error(httpx.ConnectTimeout("x"))
    assert "таймаут" in msg.lower()
    assert "ConnectTimeout" not in msg


def test_explain_llm_connect():
    from app.services.llm_gateway_errors import explain_llm_upstream_error

    msg = explain_llm_upstream_error(httpx.ConnectError("refused"))
    assert "AGENT_BASE_URL" in msg or "модель" in msg.lower()
    assert "ConnectError" not in msg


def test_explain_proxy_timeout():
    from app.proxies.pool import explain_proxy_failure

    msg = explain_proxy_failure(httpx.ConnectTimeout("x"), masked_url="http://u:***@h:1")
    assert "таймаут" in msg.lower()
    assert "ConnectTimeout" not in msg


def test_explain_proxy_auth():
    from app.proxies.pool import explain_proxy_failure

    msg = explain_proxy_failure(
        httpx.ProxyError("407 Proxy Authentication Required"),
        masked_url="http://u:***@h:1",
    )
    assert "авторизац" in msg.lower()


def test_health_check_message_without_raw_exc(monkeypatch):
    from unittest.mock import MagicMock

    from app.proxies import pool

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_cm
    mock_cm.__exit__.return_value = None
    mock_cm.get.side_effect = httpx.ConnectError("connection refused")
    monkeypatch.setattr(pool.httpx, "Client", lambda **_k: mock_cm)

    with pytest.raises(pool.ProxyError) as caught:
        pool.health_check("http://user:pass@127.0.0.1:9")
    text = str(caught.value)
    assert "ConnectError(" not in text
    assert "недоступ" in text.lower() or "подключ" in text.lower()


@pytest.fixture()
def auth_client(app_env, monkeypatch):
    from app.api import deps as api_deps
    from app.api.main import create_app
    from app.config import settings
    from app.services.llm_gateway_activity import clear_activity

    clear_activity()
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
    yield TestClient(app)
    clear_activity()


def _owner():
    return {"Authorization": "Bearer secret-token"}


def test_llm_502_russian_body(auth_client):
    with patch("app.api.routes.llm_gateway.ollama_reachable", return_value=True):
        key = auth_client.get("/api/llm-gateway/credentials", headers=_owner()).json()["api_key"]

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.request = AsyncMock(side_effect=httpx.ConnectError("boom"))

    with patch("app.api.routes.llm_gateway.httpx.AsyncClient", return_value=mock_client):
        res = auth_client.get(
            "/llm/v1/models",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert res.status_code == 502
    body = res.json()["error"]
    assert body["code"] == "upstream_unreachable"
    assert "ConnectError" not in body["message"]
    assert "модель" in body["message"].lower() or "AGENT_BASE_URL" in body["message"]

    with patch("app.api.routes.llm_gateway.ollama_reachable", return_value=True):
        recent = auth_client.get("/api/llm-gateway/credentials", headers=_owner()).json()["recent"]
    assert recent
    assert recent[0]["detail"]
    assert "ConnectError" not in recent[0]["detail"]


def test_llm_bad_key_message(auth_client):
    res = auth_client.get("/llm/v1/models", headers={"Authorization": "Bearer wrong"})
    assert res.status_code == 401
    assert "вкладки API" in res.json()["detail"]


def test_proxy_check_detail_on_failure(auth_client, app_env, monkeypatch):
    from app.proxies import pool

    monkeypatch.setattr(
        "app.proxies.pool.health_check_cached",
        lambda *a, **k: (_ for _ in ()).throw(pool.ProxyError("Прокси http://***: недоступен: тест")),
    )
    created = auth_client.post(
        "/api/proxies",
        headers=_owner(),
        json={"label": "bad-px", "url": "http://u:p@h:1", "skip_health_check": True},
    )
    assert created.status_code == 200

    checked = auth_client.post("/api/proxies/bad-px/check", headers=_owner())
    assert checked.status_code == 200
    body = checked.json()
    assert body["is_healthy"] is False
    assert body["check_detail"]
    assert "недоступен" in body["check_detail"].lower() or "прокси" in body["check_detail"].lower()
