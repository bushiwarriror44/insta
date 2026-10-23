"""Ken Burns command includes every still when several references are set."""
from pathlib import Path

from app.generation.slideshow import slideshow_ffmpeg_command


def test_slideshow_command_includes_every_image(tmp_path: Path) -> None:
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.png"
    command = slideshow_ffmpeg_command([first, second], tmp_path / "out.mp4", 6, 720, 1280)
    assert command.count("-i") == 2
    assert str(first) in command
    assert str(second) in command
    assert any("concat=n=2" in part for part in command)
