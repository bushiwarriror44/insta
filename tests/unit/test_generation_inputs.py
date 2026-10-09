"""Multimodal generation input resolution."""
import json

import pytest

from app.db.models import GenerationJob, PipelineStatus
from app.generation.base import INPUT_MODE_I2V, INPUT_MODE_SLIDESHOW, INPUT_MODE_V2V
from app.generation.chain import ChainVideoBackend
from app.services.generation_inputs import (
    apply_job_reference_fields,
    build_reference_json,
    infer_input_mode,
    resolve_generation_inputs,
)


def test_infer_input_mode_from_image_spec():
    specs = build_reference_json(reference_filename="a.jpg")
    assert infer_input_mode(None, specs) == INPUT_MODE_I2V


def test_infer_input_mode_motion_video():
    specs = [{"role": "motion_video", "filename": "clip.mp4"}]
    assert infer_input_mode(None, specs) == INPUT_MODE_V2V


def test_apply_job_reference_fields(db_session, make_account):
    job = GenerationJob(
        prompt="test",
        backend="auto",
        status=PipelineStatus.queued,
    )
    apply_job_reference_fields(
        job,
        reference_filename="ref.png",
        input_mode=INPUT_MODE_SLIDESHOW,
    )
    assert job.input_mode == INPUT_MODE_SLIDESHOW
    assert json.loads(job.reference_json)[0]["filename"] == "ref.png"


def test_resolve_generation_inputs_missing_file(db_session, app_env):
    job = GenerationJob(
        prompt="animate",
        backend="fal",
        status=PipelineStatus.queued,
        reference_json=json.dumps([{"role": "start_image", "filename": "missing.jpg"}]),
    )
    db_session.add(job)
    db_session.commit()
    from app.generation.base import GenerationError

    with pytest.raises(GenerationError, match="не найден"):
        resolve_generation_inputs(db_session, job)


def test_chain_skips_hf_for_i2v(monkeypatch):
    from app.generation.huggingface import HuggingFaceVideoBackend
    from app.generation.base import GenerationReference, GenerationRequest, INPUT_MODE_I2V
    from pathlib import Path

    hf = HuggingFaceVideoBackend()
    assert hf.supports_i2v is False
    req = GenerationRequest(
        prompt="move",
        mode=INPUT_MODE_I2V,
        references=[
            GenerationReference(role="start_image", path=Path("x.jpg"), mime="image/jpeg")
        ],
    )
    chain = ChainVideoBackend(backends=[hf])
    from app.generation.base import GenerationError

    with pytest.raises(GenerationError):
        chain.generate(req, Path("."))
