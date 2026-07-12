"""WebSocket auth and proxy tests for the interactive browser VNC endpoint."""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


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
    return TestClient(app)


class _FakeUpstream:
    """Minimal async websockify upstream that closes immediately."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def send(self, _payload):
        return None

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


def _patch_websockets_connect(monkeypatch) -> None:
    fake_module = ModuleType("websockets")

    def _connect(*_args, **_kwargs):
        return _FakeUpstream()

    fake_module.connect = _connect
    monkeypatch.setitem(sys.modules, "websockets", fake_module)


def test_vnc_ws_accepts_query_token_without_bearer_header(auth_client, monkeypatch):
    import app.api.routes.browser as browser_routes

    session = MagicMock()
    session.ws_port = 16081
    monkeypatch.setattr(browser_routes.browser_session_manager, "get", lambda _u: session)
    _patch_websockets_connect(monkeypatch)

    with auth_client.websocket_connect(
        "/api/accounts/alice/browser/vnc/ws?token=secret-token"
    ) as _ws:
        pass


def test_vnc_ws_rejects_invalid_query_token(auth_client, monkeypatch):
    import app.api.routes.browser as browser_routes

    session = MagicMock()
    session.ws_port = 16081
    monkeypatch.setattr(browser_routes.browser_session_manager, "get", lambda _u: session)
    _patch_websockets_connect(monkeypatch)

    with pytest.raises(Exception):
        with auth_client.websocket_connect(
            "/api/accounts/alice/browser/vnc/ws?token=wrong-token"
        ) as _ws:
            pass


def test_vnc_ws_requires_active_session(auth_client, monkeypatch):
    import app.api.routes.browser as browser_routes

    monkeypatch.setattr(browser_routes.browser_session_manager, "get", lambda _u: None)
    _patch_websockets_connect(monkeypatch)

    with pytest.raises(Exception):
        with auth_client.websocket_connect(
            "/api/accounts/alice/browser/vnc/ws?token=secret-token"
        ) as _ws:
            pass
