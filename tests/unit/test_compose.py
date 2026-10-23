from pathlib import Path

import pytest

from app.video.compose import ComposeError, ComposeRequest, build_command, fade_start


def test_the_fade_starts_at_the_end_not_the_beginning():
    assert fade_start(total=10.0, fade=1.5) == 8.5


def test_a_post_shorter_than_the_fade_fades_over_all_of_it():
    assert fade_start(total=1.0, fade=1.5) == 0.0


def test_every_clip_is_scaled_cropped_and_normalised():
    command = build_command(
        ComposeRequest(clips=[Path("a.mp4"), Path("b.mp4")], output=Path("out.mp4")),
        total=4.0,
    )
    filters = command[command.index("-filter_complex") + 1]
    assert filters.count("scale=1080:1920") == 2
    assert filters.count("crop=1080:1920") == 2
    assert filters.count("fps=30") == 2
    assert "concat=n=2:v=1:a=0[v]" in filters


def test_a_soundtrack_is_looped_so_the_footage_decides_the_length():
    command = build_command(
        ComposeRequest(
            clips=[Path("a.mp4")], output=Path("out.mp4"), audio=Path("music.m4a")
        ),
        total=30.0,
    )
    assert "-stream_loop" in command
    assert command[command.index("-stream_loop") + 1] == "-1"
    assert "-shortest" in command
    assert "adelay" not in command[command.index("-af") + 1]


def test_soundtrack_can_start_at_a_given_second():
    command = build_command(
        ComposeRequest(
            clips=[Path("a.mp4"), Path("b.mp4")],
            output=Path("out.mp4"),
            audio=Path("bed.mp3"),
            audio_start_s=12,
        ),
        total=30.0,
    )
    assert "adelay=12000|12000" in command[command.index("-af") + 1]


def test_no_soundtrack_means_an_explicitly_silent_file():
    command = build_command(
        ComposeRequest(clips=[Path("a.mp4")], output=Path("out.mp4")), total=4.0
    )
    assert "-an" in command


def test_a_composition_needs_a_clip():
    with pytest.raises(ComposeError, match="хотя бы один клип"):
        build_command(ComposeRequest(clips=[], output=Path("out.mp4")))
