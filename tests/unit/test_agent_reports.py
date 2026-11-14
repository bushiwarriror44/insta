"""Agent reports, error screenshots, and Telegram photos."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient


def test_error_card_and_report_roundtrip(db_session, monkeypatch):
    from app.assistant.browser_shots import write_error_card
    from app.assistant.reports import delete_agent_report, list_agent_reports, record_agent_report
    from app.config import settings

    url = write_error_card("нет аккаунта TikTok", settings)
    assert url and url.endswith(".png") or "png" in url
    name = url.split("?", 1)[0].rstrip("/").split("/")[-1]
    assert (settings.screenshots_dir / name).is_file()

    row = record_agent_report(
        db_session,
        source="panel",
        prompt="войди в TikTok",
        reply="Ошибка: нет аккаунта TikTok",
        error="нет аккаунта TikTok",
        images=[url],
        settings=settings,
    )
    assert row.status == "failed"
    assert row.screenshots == [name]
    assert list_agent_reports(db_session)[0].id == row.id
    assert delete_agent_report(db_session, row.id, settings) is True
    assert not (settings.screenshots_dir / name).exists()
    assert list_agent_reports(db_session) == []


def test_failed_report_without_image_makes_a_card(db_session, monkeypatch):
    from app.assistant.browser_shots import write_error_card
    from app.assistant.reports import record_agent_report
    from app.config import settings

    def fake_evidence(db, **kwargs):
        return write_error_card(kwargs.get("error") or "ошибка", settings)

    monkeypatch.setattr("app.assistant.reports.evidence_url", fake_evidence)
    row = record_agent_report(
        db_session,
        source="telegram",
        prompt="войди в браузер",
        reply="",
        error="Прокси не назначен",
        images=[],
        settings=settings,
    )
    assert row.status == "failed"
    assert row.screenshots
    assert (settings.screenshots_dir / row.screenshots[0]).is_file()


def test_shot_for_browser_error_only(db_session, monkeypatch):
    from app.assistant.browser_shots import shot_for_tool

    monkeypatch.setattr(
        "app.assistant.browser_shots.evidence_url",
        lambda *args, **kwargs: "/api/screenshots/shot.png?sig=1",
    )
    url = shot_for_tool(
        db_session,
        "start_browser",
        {"username": "tt"},
        {"ошибка": "Прокси не назначен"},
    )
    assert url.endswith("shot.png?sig=1")
    assert (
        shot_for_tool(db_session, "browser_status", {}, {"status": "idle"}) is None
    )


def test_send_photo_posts_file(monkeypatch, tmp_path: Path):
    from app.telegram import api_client

    picture = tmp_path / "shot.png"
    picture.write_bytes(b"\x89PNG\r\n")
    seen: dict = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"ok": True, "result": {"message_id": 9}}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, data=None, files=None):
            seen["url"] = url
            seen["caption"] = (data or {}).get("caption")
            seen["name"] = files["photo"][0]
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    message_id = api_client.send_photo("token", 42, picture, caption="Ошибка: нет входа")
    assert message_id == 9
    assert seen["url"].endswith("/sendPhoto")
    assert seen["name"] == "shot.png"
    assert "нет входа" in seen["caption"]


@pytest.fixture()
def api_client(app_env, monkeypatch):
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


def test_reports_api_lists_and_deletes(api_client: TestClient, db_session, monkeypatch):
    from app.assistant.browser_shots import write_error_card
    from app.assistant.reports import record_agent_report
    from app.config import settings

    url = write_error_card("нет сессии", settings)
    record_agent_report(
        db_session,
        source="panel",
        prompt="войти в TikTok",
        reply="Ошибка: нет сессии",
        error="нет сессии",
        images=[url],
        settings=settings,
    )
    listed = api_client.get("/api/agent-reports")
    assert listed.status_code == 200
    body = listed.json()
    assert body[0]["prompt"] == "войти в TikTok"
    assert body[0]["status"] == "failed"
    assert body[0]["screenshots"]
    removed = api_client.delete(f"/api/agent-reports/{body[0]['id']}")
    assert removed.status_code == 204
    again = api_client.get("/api/agent-reports")
    assert again.json() == []
