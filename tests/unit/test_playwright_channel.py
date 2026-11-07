from app.behavior.playwright_channel import (
    chromium_launch_channel_kwargs,
    normalize_playwright_channel,
)


def test_normalize_playwright_channel_defaults_to_chromium():
    assert normalize_playwright_channel(None) == "chromium"
    assert normalize_playwright_channel("") == "chromium"
    assert normalize_playwright_channel("CHROME") == "chrome"


def test_chromium_launch_channel_kwargs():
    assert chromium_launch_channel_kwargs("chromium") == {}
    assert chromium_launch_channel_kwargs("chrome") == {"channel": "chrome"}
