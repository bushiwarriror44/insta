"""Share one GPU between chat (Ollama) and local video."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.assistant.chat import AssistantError, _prepare_runtime
from app.config import Settings
from app.generation.base import GenerationError, GenerationRequest
from app.generation.local import LocalVideoBackend
from app.services import gpu_slot


def make_settings(tmp_path: Path, **over) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=tmp_path,
        wan_base_url=over.pop("wan_base_url", "http://gpu.example/generate"),
        agent_base_url=over.pop("agent_base_url", "http://localhost:11434/v1"),
        generation_timeout_seconds=over.pop("generation_timeout_seconds", 30),
        **over,
    )


def test_stale_lock_does_not_block_chat(tmp_path):
    settings = make_settings(tmp_path)
    path = gpu_slot.lock_path(settings)
    path.write_text(
        json.dumps({"reason": "video", "ts": 1, "stale_s": 10}),
        encoding="utf-8",
    )
    assert gpu_slot.video_busy(settings) is None
    assert not path.exists()


def test_hold_for_video_blocks_second_render(tmp_path):
    settings = make_settings(tmp_path)
    with gpu_slot.hold_for_video(settings):
        assert gpu_slot.video_busy(settings) == "video"
        with pytest.raises(GenerationError, match="занята"):
            with gpu_slot.hold_for_video(settings):
                pass
    assert gpu_slot.video_busy(settings) is None


def test_chat_refuses_while_video_holds_the_card(tmp_path):
    settings = make_settings(tmp_path)
    with gpu_slot.hold_for_video(settings):
        with pytest.raises(AssistantError, match="GPU занята рендером"):
            _prepare_runtime(settings)


def test_local_render_unloads_chat_then_posts_wan(tmp_path):
    settings = make_settings(tmp_path)
    destination_bytes = b"mp4-bytes"
    client = MagicMock()
    client.__enter__.return_value = client
    response = httpx.Response(
        200,
        content=destination_bytes,
        headers={"content-type": "video/mp4"},
        request=httpx.Request("POST", "http://gpu.example/generate"),
    )
    client.post.return_value = response
    unloaded: list[str] = []

    def fake_unload(passed=None):
        unloaded.append("yes")
        assert gpu_slot.video_busy(passed or settings) == "video"
        return ["qwen3:32b"]

    with (
        patch("app.generation.local.runtime.unload_loaded", side_effect=fake_unload),
        patch("app.generation.local.http_client", return_value=client),
    ):
        result = LocalVideoBackend(settings).generate(
            GenerationRequest(prompt="fog"),
            tmp_path,
        )

    assert unloaded == ["yes"]
    assert result.backend == "local"
    assert result.video_path.read_bytes() == destination_bytes
    assert gpu_slot.video_busy(settings) is None
    assert client.post.call_args.args[0] == "http://gpu.example/generate"
