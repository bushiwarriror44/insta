"""Tests for VNC stack command construction."""
from __future__ import annotations

from app.browser import vnc_stack as vs


def test_lightweight_x11vnc_args_avoids_invalid_framerate():
    args = vs._lightweight_x11vnc_args()
    assert "-framerate" not in args
    assert "-quality" not in args
    assert "-ncache" not in args
    assert "-wait" in args


def test_screen_with_depth_replaces_last_segment():
    assert vs._screen_with_depth("430x932x16", "24") == "430x932x24"
    assert vs._screen_with_depth("1280x800x24", "16") == "1280x800x16"


def test_xvfb_lightweight_omits_glx():
    stack = vs.VncStack(
        display=101,
        rfb_port=5901,
        ws_port=6081,
        screen="430x932x16",
        lightweight=True,
    )
    cmd = stack._xvfb_command("430x932x16")
    assert "GLX" not in cmd
    assert "+render" not in cmd


def test_xvfb_full_includes_glx():
    stack = vs.VncStack(
        display=101,
        rfb_port=5901,
        ws_port=6081,
        lightweight=False,
    )
    cmd = stack._xvfb_command("1280x800x24")
    assert "GLX" in cmd
