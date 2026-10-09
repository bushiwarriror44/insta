"""Pollinations backend: auth failures must be retryable in auto chain."""
from __future__ import annotations

from pathlib import Path
import httpx
import pytest

from app.config import Settings
from app.generation.base import GenerationError, GenerationRequest
from app.generation.pollinations import PollinationsVideoBackend


def test_pollinations_generate_uses_retryable_on_403_via_client(monkeypatch, tmp_path: Path):
    backend = PollinationsVideoBackend(
        Settings(
            pollinations_video_url="https://gen.pollinations.ai/video",
            generation_timeout_seconds=30,
        )
    )

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            return httpx.Response(403, request=httpx.Request("POST", "https://x"))

        def get(self, *a, **k):
            return httpx.Response(403, request=httpx.Request("GET", "https://x"))

    monkeypatch.setattr("app.generation.pollinations.http_client", lambda *a, **k: _Client())

    with pytest.raises(GenerationError) as exc:
        backend.generate(
            GenerationRequest(prompt="hello", duration_s=5, width=720, height=1280),
            tmp_path,
        )
    assert exc.value.retryable is True
