"""Worker-side composition jobs."""
from __future__ import annotations

from datetime import datetime, timezone

from app.config import settings
from app.db.models import (
    AssetKind,
    AssetSource,
    Composition,
    CompositionClip,
    MediaAsset,
    PipelineStatus,
)
from app.services.composing import run_composition


def _two_clip_job(db_session, app_env) -> Composition:
    media = settings.media_dir
    a = MediaAsset(filename="a.mp4", kind=AssetKind.video, source=AssetSource.generated)
    b = MediaAsset(filename="b.mp4", kind=AssetKind.video, source=AssetSource.generated)
    db_session.add_all([a, b])
    db_session.flush()
    (media / "a.mp4").write_bytes(b"mp4")
    (media / "b.mp4").write_bytes(b"mp4")
    job = Composition(status=PipelineStatus.queued, scheduled_at=datetime.now(timezone.utc))
    db_session.add(job)
    db_session.flush()
    db_session.add_all(
        [
            CompositionClip(composition_id=job.id, asset_id=a.id, position=0),
            CompositionClip(composition_id=job.id, asset_id=b.id, position=1),
        ]
    )
    db_session.commit()
    db_session.refresh(job)
    return job


def test_run_composition_success_creates_asset(db_session, app_env, monkeypatch):
    job = _two_clip_job(db_session, app_env)

    def _fake_compose(req):
        req.output.write_bytes(b"mp4")

    monkeypatch.setattr("app.services.composing.compose", _fake_compose)
    monkeypatch.setattr(
        "app.services.composing.probe_video",
        lambda _path: type("P", (), {"duration_s": 8.0, "width": 1080, "height": 1920})(),
    )

    run_composition(db_session, job, settings=settings)
    db_session.refresh(job)
    assert job.status is PipelineStatus.done
    assert job.output_asset_id is not None
    out = db_session.get(MediaAsset, job.output_asset_id)
    assert out is not None
    assert out.source is AssetSource.composed
    assert (settings.media_dir / out.filename).is_file()


def test_run_composition_fails_with_one_clip(db_session, app_env):
    media = settings.media_dir
    a = MediaAsset(filename="solo.mp4", kind=AssetKind.video, source=AssetSource.generated)
    db_session.add(a)
    db_session.flush()
    (media / "solo.mp4").write_bytes(b"mp4")
    job = Composition(status=PipelineStatus.queued, scheduled_at=datetime.now(timezone.utc))
    db_session.add(job)
    db_session.flush()
    db_session.add(CompositionClip(composition_id=job.id, asset_id=a.id, position=0))
    db_session.commit()
    db_session.refresh(job)

    run_composition(db_session, job, settings=settings)
    db_session.refresh(job)
    assert job.status in (PipelineStatus.failed, PipelineStatus.dead)
    assert "два клипа" in (job.last_error or "")
    assert job.attempts == 0


def test_run_composition_fails_missing_file(db_session, app_env):
    a = MediaAsset(filename="ghost.mp4", kind=AssetKind.video, source=AssetSource.generated)
    b = MediaAsset(filename="ghost2.mp4", kind=AssetKind.video, source=AssetSource.generated)
    db_session.add_all([a, b])
    db_session.flush()
    job = Composition(status=PipelineStatus.queued, scheduled_at=datetime.now(timezone.utc))
    db_session.add(job)
    db_session.flush()
    db_session.add_all(
        [
            CompositionClip(composition_id=job.id, asset_id=a.id, position=0),
            CompositionClip(composition_id=job.id, asset_id=b.id, position=1),
        ]
    )
    db_session.commit()
    db_session.refresh(job)

    run_composition(db_session, job, settings=settings)
    db_session.refresh(job)
    assert job.status in (PipelineStatus.failed, PipelineStatus.dead)
    assert "отсутствует" in (job.last_error or "")
