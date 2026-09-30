"""Factory interactivity: approve, week, assets, assistant route."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sqlalchemy import select

from app.db.models import (
    AssetKind,
    AssetSource,
    GenerationJob,
    MediaAsset,
    PlanJob,
    PostJob,
    PostJobStatus,
)


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
    job = db_session.scalar(select(PlanJob).order_by(PlanJob.id.desc()).limit(1))
    assert job is not None
    assert job.spread_over_days == 7


def test_preview_plan_queues_generations_without_auto_schedule(
    api_client, db_session, make_account, monkeypatch
):
    from tests.unit.test_factory_merge import StubAgent

    monkeypatch.setattr(
        "app.services.planning.get_agent",
        lambda settings=None: StubAgent(),
    )
    account = make_account()
    account.brief = "calm forests"
    db_session.commit()
    res = api_client.post(
        f"/api/accounts/{account.id}/preview",
        json={"count": 1, "duration_s": 5},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["planned"] == 1
    assert len(body["job_ids"]) == 1
    gen = db_session.get(GenerationJob, body["job_ids"][0])
    assert gen is not None
    assert gen.auto_schedule is False


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


def test_maintenance_backup_take_list_restore(api_client, app_env, monkeypatch, tmp_path):
    import sqlite3

    from app.config import settings

    live = tmp_path / "panel.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{live}", raising=True)
    monkeypatch.setattr(settings, "backup_dir", tmp_path / "backups", raising=True)

    with sqlite3.connect(live) as conn:
        conn.execute("CREATE TABLE backup_api (v INTEGER)")
        conn.execute("INSERT INTO backup_api VALUES (1)")
        conn.commit()

    created = api_client.post("/api/maintenance/backups")
    assert created.status_code == 200
    name = created.json()["name"]
    assert name.startswith("app-")
    assert (Path(settings.backup_dir) / name).is_file()

    listed = api_client.get("/api/maintenance/backups")
    assert listed.status_code == 200
    assert any(row["name"] == name for row in listed.json())

    with sqlite3.connect(live) as conn:
        conn.execute("DELETE FROM backup_api")
        conn.commit()

    restored = api_client.post("/api/maintenance/backups/restore", json={"name": name})
    assert restored.status_code == 200
    with sqlite3.connect(live) as conn:
        assert conn.execute("SELECT v FROM backup_api").fetchone()[0] == 1


def test_maintenance_restore_rejects_invalid_backup_name(api_client):
    res = api_client.post(
        "/api/maintenance/backups/restore",
        json={"name": "../../evil.db"},
    )
    assert res.status_code == 409
    res2 = api_client.post("/api/maintenance/backups/restore", json={"name": "evil.db"})
    assert res2.status_code == 409


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


def test_create_generation_and_join(api_client, db_session, app_env, monkeypatch):
    from types import SimpleNamespace

    from app.config import settings

    monkeypatch.setattr(
        "app.api.routes.factory.get_backend",
        lambda *_args, **_kwargs: SimpleNamespace(healthcheck=lambda: True),
    )
    gen = api_client.post(
        "/api/generations",
        json={
            "prompt": "mist over a ridge",
            "input_mode": "image_slideshow",
            "reference_filename": "still.jpg",
        },
    )
    assert gen.status_code == 200
    body = gen.json()
    assert body["status"] == "queued"
    assert body.get("input_mode") == "image_slideshow"
    assert body.get("backend") == "slideshow"

    (settings.media_dir / "join-a.mp4").write_bytes(b"x")
    (settings.media_dir / "join-b.mp4").write_bytes(b"x")
    asset_a = MediaAsset(filename="join-a.mp4", kind=AssetKind.video, source=AssetSource.generated)
    asset_b = MediaAsset(filename="join-b.mp4", kind=AssetKind.video, source=AssetSource.generated)
    db_session.add_all([asset_a, asset_b])
    db_session.commit()
    join = api_client.post(
        "/api/compositions",
        json={"clip_ids": [asset_a.id, asset_b.id], "post_title": "ridge"},
    )
    assert join.status_code == 200
    assert join.json()["clips"] == 2
    assert join.json()["status"] == "queued"


def test_list_generation_backends(api_client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "fal_api_key", "k")
    res = api_client.get("/api/generations/backends")
    assert res.status_code == 200
    names = [row["name"] for row in res.json()]
    assert names[0] == "auto"
    assert "fal" in names
    fal = next(row for row in res.json() if row["name"] == "fal")
    assert fal["healthy"] is True
    assert "licence" in fal
    assert "experimental" in fal


def test_api_generations_reference_filename_sanitized(api_client, db_session, monkeypatch):
    from types import SimpleNamespace

    from app.db.models import GenerationJob

    monkeypatch.setattr(
        "app.api.routes.factory.get_backend",
        lambda *_args, **_kwargs: SimpleNamespace(healthcheck=lambda: True),
    )
    res = api_client.post(
        "/api/generations",
        json={
            "prompt": "mist",
            "reference_filename": "../../../etc/passwd",
            "input_mode": "image_to_video",
        },
    )
    assert res.status_code == 200
    job = db_session.get(GenerationJob, res.json()["id"])
    assert job is not None
    import json

    refs = json.loads(job.reference_json)
    assert refs[0]["filename"] == "passwd"


def test_composition_requires_two_clips(api_client, db_session):
    from app.db.models import AssetKind, AssetSource, MediaAsset

    asset = MediaAsset(filename="solo.mp4", kind=AssetKind.video, source=AssetSource.generated)
    db_session.add(asset)
    db_session.commit()
    res = api_client.post("/api/compositions", json={"clip_ids": [asset.id]})
    assert res.status_code == 422


def test_cancel_generation_queued_only(api_client, db_session):
    from app.db.models import GenerationJob, PipelineStatus

    job = GenerationJob(prompt="x", backend="auto", status=PipelineStatus.queued)
    db_session.add(job)
    db_session.commit()
    ok = api_client.post(f"/api/generations/{job.id}/cancel")
    assert ok.status_code == 200
    assert ok.json()["status"] == "cancelled"

    running = GenerationJob(prompt="y", backend="auto", status=PipelineStatus.running)
    db_session.add(running)
    db_session.commit()
    bad = api_client.post(f"/api/generations/{running.id}/cancel")
    assert bad.status_code == 409


def test_retry_generation_requires_health(api_client, db_session, monkeypatch):
    from types import SimpleNamespace

    from app.db.models import GenerationJob, PipelineStatus

    job = GenerationJob(
        prompt="z",
        backend="fal",
        status=PipelineStatus.failed,
        attempts=3,
    )
    db_session.add(job)
    db_session.commit()
    monkeypatch.setattr(
        "app.api.routes.factory.get_backend",
        lambda *_args, **_kwargs: SimpleNamespace(
            healthcheck=lambda: False,
            health_detail=lambda: "fal не настроен",
        ),
    )
    res = api_client.post(f"/api/generations/{job.id}/retry")
    assert res.status_code == 409
    assert "не настроен" in res.json()["detail"]


def test_create_composition_rejects_removed_asset(api_client, db_session, app_env):
    from datetime import datetime, timezone

    from app.config import settings

    (settings.media_dir / "ok.mp4").write_bytes(b"x")
    (settings.media_dir / "gone.mp4").write_bytes(b"x")
    ok = MediaAsset(filename="ok.mp4", kind=AssetKind.video, source=AssetSource.generated)
    gone = MediaAsset(
        filename="gone.mp4",
        kind=AssetKind.video,
        source=AssetSource.generated,
        file_removed_at=datetime.now(timezone.utc),
    )
    db_session.add_all([ok, gone])
    db_session.commit()
    res = api_client.post("/api/compositions", json={"clip_ids": [ok.id, gone.id]})
    assert res.status_code == 404
    assert "удалён" in res.json()["detail"]


def test_cancel_composition_queued_only(api_client, db_session):
    from app.db.models import Composition, PipelineStatus

    job = Composition(status=PipelineStatus.queued)
    db_session.add(job)
    db_session.commit()
    ok = api_client.post(f"/api/compositions/{job.id}/cancel")
    assert ok.status_code == 200
    assert ok.json()["status"] == "cancelled"

    running = Composition(status=PipelineStatus.running)
    db_session.add(running)
    db_session.commit()
    bad = api_client.post(f"/api/compositions/{running.id}/cancel")
    assert bad.status_code == 409


def test_retry_composition_revives_failed(api_client, db_session):
    from app.db.models import Composition, PipelineStatus

    job = Composition(status=PipelineStatus.failed, attempts=1)
    db_session.add(job)
    db_session.commit()
    res = api_client.post(f"/api/compositions/{job.id}/retry")
    assert res.status_code == 200
    assert res.json()["status"] == "queued"


def test_create_generation_auto_rejected_when_none_healthy(api_client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "fal_api_key", "")
    monkeypatch.setattr(settings, "hf_token", "")
    monkeypatch.setattr(settings, "pollinations_video_url", "")
    monkeypatch.setattr(settings, "wan_base_url", "")
    monkeypatch.setattr(settings, "hf_space_id", "")
    res = api_client.post("/api/generations", json={"prompt": "mist"})
    assert res.status_code == 409
    assert "не настроен" in res.json()["detail"]
