"""Unit tests for Playwright mobile/desktop surface profiles."""
from __future__ import annotations

from app.behavior import playwright_surface as ps


def test_resolve_playwright_surface_defaults_to_mobile():
    assert ps.resolve_playwright_surface(None) == "mobile"
    assert ps.resolve_playwright_surface("") == "mobile"
    assert ps.resolve_playwright_surface("unknown") == "mobile"


def test_resolve_playwright_surface_desktop_aliases():
    assert ps.resolve_playwright_surface("desktop") == "desktop"
    assert ps.resolve_playwright_surface("web") == "desktop"
    assert ps.resolve_playwright_surface("pc") == "desktop"


def test_browser_launch_args_window_size():
    mobile = ps.browser_launch_args("mobile")
    desktop = ps.browser_launch_args("desktop")
    assert any("430,932" in arg for arg in mobile)
    assert any("1280,800" in arg for arg in desktop)


def test_stealth_init_script_touch_points():
    assert "maxTouchPoints" in ps.stealth_init_script("mobile")
    assert "5" in ps.stealth_init_script("mobile")
    assert "0" in ps.stealth_init_script("desktop")


def test_playwright_context_kwargs_mobile():
    fingerprint = type(
        "FP",
        (),
        {
            "locale": "en-US",
            "settings": {
                "device_settings": {
                    "android_release": "13",
                    "model": "SM-S908B",
                    "resolution": "1080x2400",
                }
            },
        },
    )()
    kwargs = ps.playwright_context_kwargs(
        "mobile",
        fingerprint=fingerprint,
        locale="en-US",
        timezone_id="America/New_York",
    )
    assert kwargs["is_mobile"] is True
    assert kwargs["has_touch"] is True
    assert kwargs["device_scale_factor"] == 3
    assert "Mobile Safari" in kwargs["user_agent"]
    assert kwargs["viewport"]["width"] >= 320
    assert kwargs["viewport"]["height"] >= 640


def test_playwright_context_kwargs_desktop():
    kwargs = ps.playwright_context_kwargs(
        "desktop",
        fingerprint=None,
        locale="en-US",
        timezone_id="UTC",
    )
    assert kwargs["is_mobile"] is False
    assert kwargs["has_touch"] is False
    assert kwargs["device_scale_factor"] == 1
    assert "Windows NT" in kwargs["user_agent"]
    assert kwargs["viewport"] == {"width": 1280, "height": 800}


def test_vnc_screen_size():
    assert ps.vnc_screen_size("mobile") == "430x932x24"
    assert ps.vnc_screen_size("desktop") == "1280x800x24"
