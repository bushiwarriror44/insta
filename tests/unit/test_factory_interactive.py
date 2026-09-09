"""Factory interactivity: approve, week, assets, assistant route."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.db.models import AssetKind, AssetSource, MediaAsset, PostJob, PostJobStatus


@pytest.fixture()
def api_client(app_env, monkeypatch):
    from app.api import deps as api_deps
    from app.api.main import create_app
    from app.config import settings

    monkeypatch.setattr(settings, "admin_token", "", raising=True)
    monkeypatch.setattr(settings, "worker_autostart", False, raising=True)

    app = create_app()

    def _override_get_db():
        db = app_env.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[api_deps.get_db] = _override_get_db
    return TestClient(app)


def test_week_plan_sets_spread(api_client, db_session, make_account):
    account = make_account()
    res = api_client.post(f"/api/accounts/{account.id}/week", json={"count": 4})
    assert res.status_code == 200
    assert res.json()["count"] == 4


def test_approve_releases_a_held_post(api_client, db_session, make_account, app_env):
    account = make_account()
    job = PostJob(
        account_id=account.id,
        source_video_path=str(app_env.video_source_dir / "clip.mp4"),
        scheduled_for=datetime.now(timezone.utc),
        status=PostJobStatus.awaiting_review,
        title="held",
    )
    db_session.add(job)
    db_session.commit()
    res = api_client.post(f"/api/jobs/{job.id}/approve")
    assert res.status_code == 200
    assert res.json()["status"] == "queued"


def test_hold_for_review_on_account_settings(api_client, db_session, make_account):
    account = make_account()
    res = api_client.patch(
        f"/api/accounts/{account.id}/agent-settings",
        json={"hold_for_review": True, "daily_spend_cap_usd": 2.5},
    )
    assert res.status_code == 200
    assert res.json()["hold_for_review"] is True
    db_session.refresh(account)
    assert account.hold_for_review is True


def test_assets_list_includes_generated(api_client, db_session):
    db_session.add(
        MediaAsset(
            filename="gen.mp4",
            kind=AssetKind.video,
            source=AssetSource.generated,
            label="misty",
            prompt="fog over a ridge",
        )
    )
    db_session.commit()
    res = api_client.get("/api/assets")
    assert res.status_code == 200
    assert any(row["filename"] == "gen.mp4" for row in res.json())


def test_assistant_route_is_mounted(api_client):
    spec = api_client.get("/api/openapi.json")
    assert spec.status_code == 200
    assert "/api/assistant" in spec.json()["paths"]


def test_maintenance_runtime_route(api_client):
    res = api_client.get("/api/maintenance/runtime")
    assert res.status_code == 200
    assert "reachable" in res.json()


def test_answer_question(api_client, db_session, make_account):
    from app.db.models import Clarification

    account = make_account()
    question = Clarification(
        account_id=account.id,
        question="какой вайб?",
        question_key="какой вайб",
    )
    db_session.add(question)
    db_session.commit()
    res = api_client.post(f"/api/questions/{question.id}/answer", json={"answer": "спокойный туман"})
    assert res.status_code == 200
    assert res.json()["answer"] == "спокойный туман"


def test_create_generation_and_join(api_client, db_session, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.api.routes.factory.get_backend",
        lambda *_args, **_kwargs: SimpleNamespace(healthcheck=lambda: True),
    )
    gen = api_client.post("/api/generations", json={"prompt": "mist over a ridge"})
    assert gen.status_code == 200
    assert gen.json()["status"] == "queued"

    asset = MediaAsset(filename="join-a.mp4", kind=AssetKind.video, source=AssetSource.generated)
    db_session.add(asset)
    db_session.commit()
    join = api_client.post("/api/compositions", json={"clip_ids": [asset.id], "post_title": "ridge"})
    assert join.status_code == 200
    assert join.json()["clips"] == 1
    assert join.json()["status"] == "queued"
