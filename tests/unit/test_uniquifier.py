"""Tests for app.video.uniquifier (subprocess-mocked)."""
from __future__ import annotations

import json
import subprocess

import pytest

from app.video import uniquifier as un
from app.video.uniquifier import (
    UniquifyParams,
    VideoMeta,
    _build_audio_filters,
    _build_video_filters,
    probe,
    random_params,
    uniquify,
)


def test_random_params_within_documented_ranges():
    for _ in range(30):
        p = random_params(allow_mirror=False)
        assert 0.5 <= p.crop_left_pct <= 3.0
        assert 0.5 <= p.crop_right_pct <= 3.0
        assert 0.5 <= p.crop_top_pct <= 3.0
        assert 0.5 <= p.crop_bottom_pct <= 3.0
        assert 1.005 <= p.zoom <= 1.03
        assert p.mirror is False
        assert -0.03 <= p.brightness <= 0.03
        assert 0.97 <= p.contrast <= 1.03
        assert 0.97 <= p.saturation <= 1.03
        assert 0.97 <= p.gamma <= 1.03
        assert -3.0 <= p.audio_pitch_cents <= 3.0
        assert -0.5 <= p.audio_volume_db <= 0.5
        assert 0.99 <= p.audio_atempo <= 1.01
        assert 20 <= p.crf <= 24
        assert p.preset in {"medium", "fast", "slow", "veryfast"}
        assert p.audio_bitrate_kbps in {96, 112, 128, 144, 160, 192}
        assert 48 <= p.keyint <= 90
        assert 0 <= p.trim_start_ms <= 250
        assert 30 <= p.trim_end_ms <= 300


def test_random_params_allow_mirror_can_be_true():
    saw_true = False
    for _ in range(500):
        p = random_params(allow_mirror=True)
        if p.mirror:
            saw_true = True
            break
    assert saw_true


def test_probe_parses_full_streams(fake_subprocess):
    fake_subprocess["state"]["probe_payload"] = {
        "streams": [
            {"codec_type": "video", "width": 720, "height": 1280, "r_frame_rate": "60/1"},
            {"codec_type": "audio"},
        ],
        "format": {"duration": "12.5"},
    }
    meta = probe("any.mp4")
    assert meta.width == 720
    assert meta.height == 1280
    assert meta.fps == 60.0
    assert meta.duration_sec == 12.5
    assert meta.has_audio is True


def test_probe_handles_missing_audio(fake_subprocess):
    fake_subprocess["state"]["probe_payload"] = {
        "streams": [{"codec_type": "video", "width": 1080, "height": 1920, "r_frame_rate": "30/1"}],
        "format": {"duration": "3.0"},
    }
    meta = probe("any.mp4")
    assert meta.has_audio is False


def test_probe_handles_zero_division(fake_subprocess):
    fake_subprocess["state"]["probe_payload"] = {
        "streams": [{"codec_type": "video", "width": 1080, "height": 1920, "r_frame_rate": "30/0"}],
        "format": {"duration": "3.0"},
    }
    meta = probe("any.mp4")
    assert meta.fps == 30.0


def test_build_video_filters_includes_pipeline():
    meta = VideoMeta(width=1080, height=1920, duration_sec=5.0, fps=30, has_audio=True)
    p = UniquifyParams(
        crop_left_pct=2.0, crop_right_pct=2.0, crop_top_pct=2.0, crop_bottom_pct=2.0,
        zoom=1.02, mirror=True, brightness=0.01, contrast=1.01, saturation=1.0, gamma=1.0,
    )
    out = _build_video_filters(meta, p)
    assert "crop=" in out
    assert "scale=" in out
    assert "hflip" in out
    assert "format=yuv420p" in out
    assert "eq=" in out


def test_build_video_filters_skips_eq_when_neutral():
    meta = VideoMeta(width=1080, height=1920, duration_sec=5.0, fps=30, has_audio=True)
    p = UniquifyParams()  # all defaults => neutral
    out = _build_video_filters(meta, p)
    assert "eq=" not in out


def test_build_video_filters_handles_zero_dimensions():
    meta = VideoMeta(width=0, height=0, duration_sec=5.0, fps=30, has_audio=True)
    p = UniquifyParams()
    out = _build_video_filters(meta, p)
    assert "crop=" in out


def test_build_audio_filters_pitch_uses_atempo_inverse():
    p = UniquifyParams(audio_pitch_cents=1.0)
    out = _build_audio_filters(p)
    assert out is not None
    assert "asetrate=" in out
    assert "aresample=44100" in out
    assert "atempo=" in out


def test_build_audio_filters_returns_none_when_neutral():
    p = UniquifyParams()  # all defaults
    out = _build_audio_filters(p)
    assert out is None


def test_uniquify_constructs_correct_ffmpeg_command(fake_subprocess, app_env):
    src = app_env.video_source_dir / "in.mp4"
    src.write_bytes(b"x")
    dst = app_env.video_out_dir / "out.mp4"
    used = uniquify(src, dst, allow_mirror=False)
    assert used.crf >= 20

    run_calls = fake_subprocess["run"]
    assert run_calls, "ffmpeg run should have been invoked"
    cmd = run_calls[-1]
    assert "-map_metadata" in cmd
    assert cmd[cmd.index("-map_metadata") + 1] == "-1"
    assert "-c:v" in cmd
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert "-pix_fmt" in cmd
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
    assert "-movflags" in cmd
    assert cmd[cmd.index("-movflags") + 1] == "+faststart"
    metadata_args = [c for c in cmd if c.startswith("creation_time=")]
    assert metadata_args


def test_uniquify_audio_branches(fake_subprocess, app_env):
    src = app_env.video_source_dir / "in.mp4"
    src.write_bytes(b"x")
    dst = app_env.video_out_dir / "out.mp4"

    fake_subprocess["state"]["probe_payload"] = {
        "streams": [{"codec_type": "video", "width": 1080, "height": 1920, "r_frame_rate": "30/1"}],
        "format": {"duration": "5.0"},
    }
    uniquify(src, dst, allow_mirror=False)
    cmd = fake_subprocess["run"][-1]
    assert "-an" in cmd
    assert "-c:a" not in cmd


def test_uniquify_audio_present_branch(fake_subprocess, app_env):
    src = app_env.video_source_dir / "in.mp4"
    src.write_bytes(b"x")
    dst = app_env.video_out_dir / "out.mp4"
    fake_subprocess["state"]["probe_payload"] = {
        "streams": [
            {"codec_type": "video", "width": 1080, "height": 1920, "r_frame_rate": "30/1"},
            {"codec_type": "audio"},
        ],
        "format": {"duration": "5.0"},
    }
    uniquify(src, dst, allow_mirror=False)
    cmd = fake_subprocess["run"][-1]
    assert "-c:a" in cmd
    assert cmd[cmd.index("-c:a") + 1] == "aac"


def test_uniquify_raises_on_ffmpeg_failure(fake_subprocess, app_env):
    src = app_env.video_source_dir / "in.mp4"
    src.write_bytes(b"x")
    dst = app_env.video_out_dir / "out.mp4"
    fake_subprocess["state"]["run_returncode"] = 1
    fake_subprocess["state"]["run_stderr"] = b"boom"
    with pytest.raises(subprocess.CalledProcessError):
        uniquify(src, dst, allow_mirror=False)


def test_uniquify_missing_source(app_env):
    with pytest.raises(FileNotFoundError):
        uniquify(app_env.video_source_dir / "nope.mp4", app_env.video_out_dir / "x.mp4")


def test_ffprobe_bin_raises_when_missing(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError):
        un.ffprobe_bin()


def test_ffprobe_bin_returns_path_when_present(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/ffprobe")
    assert un.ffprobe_bin() == "/usr/bin/ffprobe"


def test_uniquify_short_video_skips_trim(fake_subprocess, app_env):
    src = app_env.video_source_dir / "in.mp4"
    src.write_bytes(b"x")
    dst = app_env.video_out_dir / "out.mp4"
    fake_subprocess["state"]["probe_payload"] = {
        "streams": [
            {"codec_type": "video", "width": 1080, "height": 1920, "r_frame_rate": "30/1"},
            {"codec_type": "audio"},
        ],
        "format": {"duration": "0.4"},
    }
    used = uniquify(src, dst, allow_mirror=False)
    assert used.trim_start_ms == 0
    assert used.trim_end_ms == 0


def test_uniquify_explicit_params_used(fake_subprocess, app_env):
    src = app_env.video_source_dir / "in.mp4"
    src.write_bytes(b"x")
    dst = app_env.video_out_dir / "out.mp4"
    custom = UniquifyParams(crf=21, preset="slow", audio_bitrate_kbps=160, keyint=72,
                            creation_time_iso="2026-01-01T00:00:00")
    uniquify(src, dst, params=custom)
    cmd = fake_subprocess["run"][-1]
    assert "-crf" in cmd
    assert cmd[cmd.index("-crf") + 1] == "21"
    assert cmd[cmd.index("-preset") + 1] == "slow"


# ---------------------------------------------------------------------------
# Anti-detection extensions: EQ, resolution jitter, watermark crop.
# ---------------------------------------------------------------------------


def test_audio_filters_include_equalizer_band():
    p = UniquifyParams(audio_eq_freq=400, audio_eq_gain=1.2)
    out = _build_audio_filters(p)
    assert out is not None
    assert "equalizer=f=400" in out
    # gain rounded to 3 decimal places
    assert "g=1.200" in out


def test_audio_filters_skip_equalizer_when_gain_zero():
    p = UniquifyParams(audio_eq_freq=400, audio_eq_gain=0.0)
    out = _build_audio_filters(p)
    assert out is None or "equalizer" not in out


def test_video_filters_apply_watermark_drawbox():
    """When ``assume_tiktok_watermark`` is set, the filter chain must paint
    a black box over the upper-right ~12 %×8 % rectangle."""
    meta = VideoMeta(width=1080, height=1920, duration_sec=5.0, fps=30, has_audio=True)
    p = UniquifyParams(assume_tiktok_watermark=True)
    out = _build_video_filters(meta, p)
    assert "drawbox=" in out


def test_video_filters_resolution_jitter_round_trip():
    meta = VideoMeta(width=1080, height=1920, duration_sec=5.0, fps=30, has_audio=True)
    p = UniquifyParams(resolution_jitter_pct=1.005)
    out = _build_video_filters(meta, p)
    # Expect at least two scale=… invocations (jitter scale + return to original).
    assert out.count("scale=") >= 2


def test_video_filters_no_jitter_when_neutral():
    meta = VideoMeta(width=1080, height=1920, duration_sec=5.0, fps=30, has_audio=True)
    p = UniquifyParams(resolution_jitter_pct=1.0)
    out = _build_video_filters(meta, p)
    # Default chain: 1 baseline scale (= original size) and an optional one
    # for the zoom branch. Without jitter we shouldn't see *3* scales though.
    assert out.count("scale=") <= 2
