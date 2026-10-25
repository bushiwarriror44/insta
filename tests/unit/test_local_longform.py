"""Local Wan longform: segment split, continuation prompt, soft join."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from app.config import Settings
from app.generation.base import GenerationRequest
from app.generation.local import LocalVideoBackend
from app.generation.local_longform import continuation_prompt, segment_durations
from app.video.compose import ComposeRequest, build_command


@contextmanager
def _hold(*_args, **_kwargs):
    yield


def test_sixty_seconds_becomes_six_ten_second_segments():
    assert segment_durations(60) == [10.0, 10.0, 10.0, 10.0, 10.0, 10.0]


def test_twenty_five_seconds_becomes_ten_ten_five():
    assert segment_durations(25) == [10.0, 10.0, 5.0]


def test_continuation_prompt_marks_segment_two_of_six():
    text = continuation_prompt("fog over a ridge", 2, 6, 60)
    assert "Segment 2/6" in text
    assert "fog over a ridge" in text
    assert "do not restart the scene" in text


def test_build_command_uses_xfade_when_fade_is_set():
    command = build_command(
        ComposeRequest(
            clips=[Path("a.mp4"), Path("b.mp4"), Path("c.mp4")],
            output=Path("out.mp4"),
            video_fade_s=0.5,
            clip_durations=[10.0, 10.0, 10.0],
        ),
        total=30.0,
    )
    filters = command[command.index("-filter_complex") + 1]
    assert "xfade=transition=fade:duration=0.500" in filters
    assert "concat=" not in filters


def test_build_command_keeps_hard_concat_without_fade():
    command = build_command(
        ComposeRequest(clips=[Path("a.mp4"), Path("b.mp4")], output=Path("out.mp4")),
        total=20.0,
    )
    filters = command[command.index("-filter_complex") + 1]
    assert "concat=n=2:v=1:a=0[v]" in filters
    assert "xfade" not in filters


def test_local_thirty_seconds_calls_wan_three_times_and_stitches(tmp_path: Path):
    settings = Settings(
        wan_base_url="https://tabasco.example.salad.cloud/generate",
        generation_poll_seconds=0,
        generation_timeout_seconds=30,
    )
    backend = LocalVideoBackend(settings)
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16

    def post(_url, **_kwargs):
        return httpx.Response(202, json={"job_id": "job"})

    def get(url, **_kwargs):
        if url.endswith("/file"):
            return httpx.Response(200, content=mp4, headers={"content-type": "video/mp4"})
        return httpx.Response(200, json={"status": "done", "error": ""})

    client.post.side_effect = post
    client.get.side_effect = get
    stitched = tmp_path / "stitched.mp4"
    stitched.write_bytes(mp4)

    with (
        patch.object(backend, "healthcheck", return_value=True),
        patch("app.generation.local.hold_for_video", _hold),
        patch("app.generation.local.runtime.unload_loaded"),
        patch("app.generation.local.touch"),
        patch("app.generation.local.http_client", return_value=client),
        patch("app.generation.local.stitch_segments", return_value=stitched) as stitch,
    ):
        result = backend.generate(
            GenerationRequest(prompt="fog over a ridge", duration_s=30, seed=7),
            tmp_path,
        )

    assert result.video_path == stitched
    assert client.post.call_count == 3
    bodies = [call.kwargs["json"] for call in client.post.call_args_list]
    assert all(body["seed"] == 7 for body in bodies)
    assert all(body["duration_s"] == 10.0 for body in bodies)
    assert "Segment 1/3" in bodies[0]["prompt"]
    assert "Segment 2/3" in bodies[1]["prompt"]
    assert "Segment 3/3" in bodies[2]["prompt"]
    stitch.assert_called_once()
    assert stitch.call_args.kwargs["clip_durations"] == [10.0, 10.0, 10.0]
