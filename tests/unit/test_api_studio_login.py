"""API first-login for YouTube/TikTok."""
import pytest
from fastapi.testclient import TestClient

from app.api.schemas import FirstLoginOut
from app.db.models import Platform


@pytest.fixture()
def api_client(app_env, monkeypatch):
    from app.api import deps as api_deps
    from app.api.main import create_app
    from app.config import settings

    monkeypatch.setattr(settings, "admin_token", "", raising=True)
    monkeypatch.setattr("app.proxies.pool.health_check", lambda *a, **kw: {"ip": "203.0.113.5"})
    monkeypatch.setattr(
        "app.api.routes.accounts.ensure_fingerprint_and_proxy",
        lambda username, country="US", **kwargs: object(),
    )
    app = create_app()

    def _override_get_db():
        db = app_env.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[api_deps.get_db] = _override_get_db
    return TestClient(app)


def test_first_login_youtube_routes_studio(
    api_client, db_session, make_account, make_proxy, monkeypatch
):
    proxy = make_proxy(label="px-yt-api")
    make_account(username="ytapi", proxy=proxy, platform=Platform.youtube, password="secret")
    monkeypatch.setattr(
        "app.behavior.warmup_playwright.playwright_browsers_available",
        lambda: True,
    )

    def _studio(account, db, *, on_status=None):
        return FirstLoginOut(run_id=5, ok=True, session_imported=True, logs=[])

    monkeypatch.setattr("app.accounts.studio_login_service.run_studio_login", _studio)
    res = api_client.post("/api/accounts/ytapi/first-login")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["run_id"] == 5


def test_put_session_rejected_for_youtube_preserves_playwright_state(
    api_client, make_account, make_proxy, app_env
):
    from app.accounts.playwright_session import playwright_state_path, save_playwright_state

    proxy = make_proxy(label="px-yt-sess")
    make_account(username="ytsess", proxy=proxy, platform=Platform.youtube, password="secret")
    save_playwright_state(
        "ytsess",
        {"cookies": [{"name": "SID", "value": "x", "domain": ".youtube.com"}], "origins": []},
    )
    path = playwright_state_path("ytsess")
    assert path.exists()

    res = api_client.put(
        "/api/accounts/ytsess/session",
        json={"session_id": "a" * 40},
    )
    assert res.status_code == 400
    assert "Instagram" in res.json()["detail"]
    assert path.exists()


def test_create_account_rejects_session_id_for_youtube(api_client):
    api_client.post(
        "/api/proxies",
        json={"label": "px-yt-create", "url": "http://u:p@h:1", "skip_health_check": True},
    )
    res = api_client.post(
        "/api/accounts",
        json={
            "username": "ytnew",
            "password": "secret",
            "proxy_label": "px-yt-create",
            "platform": "youtube",
            "session_id": "b" * 40,
        },
    )
    assert res.status_code == 400
    assert "Instagram" in res.json()["detail"]
