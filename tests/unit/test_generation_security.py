"""QA: generation reference paths must stay inside library."""
import json

import pytest

from app.db.models import AssetKind, AssetSource, GenerationJob, MediaAsset, PipelineStatus
from app.generation.base import GenerationError
from app.services.generation_inputs import resolve_generation_inputs


def test_reference_rejects_path_traversal(db_session, app_env):
    job = GenerationJob(
        prompt="x",
        backend="auto",
        status=PipelineStatus.queued,
        reference_json=json.dumps([{"role": "start_image", "filename": "../../../etc/passwd"}]),
    )
    db_session.add(job)
    db_session.commit()
    with pytest.raises(GenerationError):
        resolve_generation_inputs(db_session, job)


def test_reference_asset_id_rejects_path_traversal(db_session, app_env):
    asset = MediaAsset(
        filename="../../../outside.mp4",
        kind=AssetKind.video,
        source=AssetSource.upload,
    )
    db_session.add(asset)
    db_session.commit()
    job = GenerationJob(
        prompt="x",
        backend="auto",
        status=PipelineStatus.queued,
        reference_json=json.dumps([{"role": "start_image", "asset_id": asset.id}]),
    )
    db_session.add(job)
    db_session.commit()
    with pytest.raises(GenerationError, match="escapes|отсутствует"):
        resolve_generation_inputs(db_session, job)
