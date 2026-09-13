from pathlib import Path

import pytest

from app.config import Settings
from app.generation.base import GenerationError, GenerationRequest, GenerationResult, VideoBackend
from app.generation.chain import ChainVideoBackend
from app.generation.registry import available_backends, describe_backends, parse_chain
from app.db.models import GenerationJob, PipelineStatus
from app.services.generation import run_generation_job


class FakeEngine(VideoBackend):
    model_licence = "test"

    def __init__(
        self,
        name: str,
        *,
        healthy: bool = True,
        error: str | None = None,
        retryable: bool = True,
    ) -> None:
        self.name = name
        self._healthy = healthy
        self._error = error
        self._retryable = retryable
        self.calls = 0

    def healthcheck(self) -> bool:
        return self._healthy

    def health_detail(self) -> str:
        if self._healthy:
            return ""
        return f"{self.name} не настроен — задайте его API-ключ"

    def generate(self, request, out_dir: Path, on_progress=None) -> GenerationResult:
        self.calls += 1
        if self._error:
            raise GenerationError(self._error, retryable=self._retryable)
        path = out_dir / f"{self.name}.mp4"
        path.write_bytes(b"mp4")
        return GenerationResult(video_path=path, generator=f"{self.name}-model", backend=self.name)


def test_parse_chain_skips_auto_and_unknown():
    settings = Settings(video_backend_chain="auto,fal,nope,huggingface")
    assert parse_chain(settings) == ["fal", "huggingface"]


def test_available_backends_starts_with_auto():
    assert available_backends()[0] == "auto"
    assert "fal" in available_backends()
    assert "huggingface" in available_backends()


def test_chain_skips_retryable_and_returns_next(tmp_path):
    first = FakeEngine("one", error="busy", retryable=True)
    second = FakeEngine("two")
    chain = ChainVideoBackend(Settings(), backends=[first, second])
    result = chain.generate(GenerationRequest(prompt="fog"), tmp_path)
    assert first.calls == 1
    assert second.calls == 1
    assert result.backend == "two"
    assert result.video_path.name == "two.mp4"


def test_chain_stops_on_non_retryable(tmp_path):
    first = FakeEngine("one", error="bad prompt", retryable=False)
    second = FakeEngine("two")
    chain = ChainVideoBackend(Settings(), backends=[first, second])
    with pytest.raises(GenerationError, match="bad prompt"):
        chain.generate(GenerationRequest(prompt="fog"), tmp_path)
    assert second.calls == 0


def test_chain_lists_failures_when_all_retryable(tmp_path):
    chain = ChainVideoBackend(
        Settings(),
        backends=[
            FakeEngine("one", error="429", retryable=True),
            FakeEngine("two", error="timeout", retryable=True),
        ],
    )
    with pytest.raises(GenerationError, match="one: 429") as exc:
        chain.generate(GenerationRequest(prompt="fog"), tmp_path)
    assert "two: timeout" in str(exc.value)
    assert exc.value.retryable is True


def test_chain_healthcheck_any_child():
    chain = ChainVideoBackend(
        Settings(),
        backends=[FakeEngine("one", healthy=False), FakeEngine("two", healthy=True)],
    )
    assert chain.healthcheck() is True
    dead = ChainVideoBackend(Settings(), backends=[FakeEngine("one", healthy=False)])
    assert dead.healthcheck() is False
    assert "ни один рендер-бэкенд не настроен" in dead.health_detail()
    assert "API-ключ" in dead.health_detail()


def test_run_generation_job_writes_actual_backend(db_session, app_env, monkeypatch):
    from app.config import settings

    job = GenerationJob(prompt="fog", backend="auto", status=PipelineStatus.queued)
    db_session.add(job)
    db_session.commit()
    chain = ChainVideoBackend(
        settings,
        backends=[FakeEngine("fal", error="down", retryable=True), FakeEngine("huggingface")],
    )
    run_generation_job(db_session, job, backend=chain, settings=settings)
    db_session.refresh(job)
    assert job.status is PipelineStatus.done
    assert job.backend == "huggingface"


def test_describe_backends_includes_auto():
    rows = describe_backends(Settings(fal_api_key="", hf_token="", pollinations_video_url="", wan_base_url="", hf_space_id=""))
    names = [row["name"] for row in rows]
    assert names[0] == "auto"
    auto = rows[0]
    assert auto["healthy"] is False
    assert "ни один" in str(auto["detail"])
