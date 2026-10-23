"""Soundtrack mux copies the video stream and adds either lavfi or a file."""
from pathlib import Path

from app.video.mux_audio import mux_command


def test_generate_command_copies_video_and_uses_lavfi(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    out = tmp_path / "with-audio.mp4"
    command = mux_command(video, out, mode="generate", audio=None, duration_s=5.0)
    assert "-c:v" in command and command[command.index("-c:v") + 1] == "copy"
    assert "lavfi" in command
    assert any("anoisesrc" in part for part in command)
    assert any("sine=" in part for part in command)


def test_library_command_copies_video_and_uses_the_file(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    audio = tmp_path / "bed.mp3"
    out = tmp_path / "with-audio.mp4"
    command = mux_command(video, out, mode="library", audio=audio, duration_s=8.0)
    assert "-c:v" in command and command[command.index("-c:v") + 1] == "copy"
    assert str(audio) in command
    assert "-shortest" in command
    assert "lavfi" not in command
