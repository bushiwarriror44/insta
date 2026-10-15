"""Local Wan through Salad uses short async calls instead of one long POST."""

from __future__ import annotations

import importlib.util
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from app.config import Settings
from app.generation.base import GenerationError, GenerationRequest
from app.generation.local import LocalVideoBackend

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16


@contextmanager
def _hold(*_args, **_kwargs):
    yield


def _settings(**over) -> Settings:
    return Settings(
        wan_base_url=over.pop(
            "wan_base_url",
            "https://tabasco.example.salad.cloud/generate",
        ),
        generation_poll_seconds=over.pop("generation_poll_seconds", 0),
        generation_timeout_seconds=over.pop("generation_timeout_seconds", 30),
        **over,
    )


def _client() -> MagicMock:
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    return client


def _generate(backend: LocalVideoBackend, client: MagicMock, out_dir: Path):
    with (
        patch.object(backend, "healthcheck", return_value=True),
        patch("app.generation.local.hold_for_video", _hold),
        patch("app.generation.local.runtime.unload_loaded"),
        patch("app.generation.local.touch"),
        patch("app.generation.local.http_client", return_value=client),
    ):
        return backend.generate(GenerationRequest(prompt="fog over a ridge"), out_dir)


def test_salad_host_submits_async_then_downloads(tmp_path: Path):
    backend = LocalVideoBackend(_settings())
    client = _client()
    client.post.return_value = httpx.Response(202, json={"job_id": "abc"})
    client.get.side_effect = [
        httpx.Response(524, text="timeout"),
        httpx.Response(200, json={"status": "running", "error": ""}),
        httpx.Response(200, json={"status": "done", "error": ""}),
        httpx.Response(200, content=MP4, headers={"content-type": "video/mp4"}),
    ]
    result = _generate(backend, client, tmp_path)
    assert result.video_path.is_file()
    assert result.video_path.read_bytes() == MP4
    assert client.post.call_args.kwargs["headers"]["X-Async"] == "1"
    assert client.post.call_args.args[0].endswith("/generate")
    assert "/jobs/abc" in client.get.call_args_list[1].args[0]
    assert client.get.call_args_list[-1].args[0].endswith("/jobs/abc/file")


def test_wan_async_flag_polls_a_direct_gpu(tmp_path: Path):
    backend = LocalVideoBackend(
        _settings(wan_base_url="https://gpu.internal/generate", wan_async=True)
    )
    client = _client()
    client.post.return_value = httpx.Response(202, json={"job_id": "z"})
    client.get.side_effect = [
        httpx.Response(200, json={"status": "done", "error": ""}),
        httpx.Response(200, content=MP4, headers={"content-type": "video/mp4"}),
    ]
    result = _generate(backend, client, tmp_path)
    assert result.backend == "local"
    assert result.video_path.stat().st_size == len(MP4)


def test_salad_retries_while_the_gpu_is_busy(tmp_path: Path):
    backend = LocalVideoBackend(_settings(generation_timeout_seconds=30))
    client = _client()
    client.post.side_effect = [
        httpx.Response(409, json={"detail": "GPU already rendering"}),
        httpx.Response(202, json={"job_id": "later"}),
    ]
    client.get.side_effect = [
        httpx.Response(200, json={"status": "done", "error": ""}),
        httpx.Response(409, json={"detail": "job is not ready"}),
        httpx.Response(200, content=MP4, headers={"content-type": "video/mp4"}),
    ]
    result = _generate(backend, client, tmp_path)
    assert result.video_path.read_bytes() == MP4
    assert client.post.call_count == 2


def test_salad_200_without_job_means_the_gpu_image_is_old(tmp_path: Path):
    backend = LocalVideoBackend(_settings())
    client = _client()
    client.post.return_value = httpx.Response(
        200,
        content=MP4,
        headers={"content-type": "video/mp4"},
    )
    try:
        _generate(backend, client, tmp_path)
    except GenerationError as exc:
        assert "без async API" in str(exc)
        assert exc.retryable is False
    else:
        raise AssertionError("expected GenerationError")


def test_direct_gpu_stays_synchronous(tmp_path: Path):
    backend = LocalVideoBackend(_settings(wan_base_url="https://gpu.internal/generate"))
    client = _client()
    client.post.return_value = httpx.Response(
        200,
        content=MP4,
        headers={"content-type": "video/mp4"},
    )
    result = _generate(backend, client, tmp_path)
    assert result.video_path.read_bytes() == MP4
    client.get.assert_not_called()
    assert "X-Async" not in (client.post.call_args.kwargs.get("headers") or {})


def _load_generate_server(tmp_path: Path):
    path = Path(__file__).resolve().parents[2] / "docker" / "salad-gpu" / "generate_server.py"
    spec = importlib.util.spec_from_file_location("salad_generate_server_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    wan = tmp_path / "wan"
    ckpt = tmp_path / "ckpt"
    wan.mkdir()
    ckpt.mkdir()
    (wan / "generate.py").write_text("# stub\n", encoding="utf-8")
    module.WAN_DIR = wan
    module.WAN_CKPT = ckpt
    module.jobs.clear()
    return module


def test_generate_server_async_job_returns_the_file(tmp_path: Path, monkeypatch):
    module = _load_generate_server(tmp_path)

    def fake_run(cmd, **_kwargs):
        out = Path(cmd[cmd.index("--save_file") + 1])
        out.write_bytes(MP4)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    from fastapi.testclient import TestClient

    client = TestClient(module.app)
    created = client.post(
        "/generate",
        json={"prompt": "a quiet street"},
        headers={"X-Async": "1"},
    )
    assert created.status_code == 202
    job_id = created.json()["job_id"]
    status = ""
    for _ in range(50):
        status = client.get(f"/generate/jobs/{job_id}").json()["status"]
        if status in {"done", "failed"}:
            break
        time.sleep(0.02)
    assert status == "done"
    downloaded = client.get(f"/generate/jobs/{job_id}/file")
    assert downloaded.status_code == 200
    assert downloaded.content == MP4
    assert module.lock.acquire(blocking=False)
    module.lock.release()
