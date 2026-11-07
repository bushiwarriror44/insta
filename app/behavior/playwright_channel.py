"""Playwright browser channel (bundled Chromium vs system Google Chrome)."""
from __future__ import annotations

from typing import Any, Literal

PlaywrightBrowserChannel = Literal["chromium", "chrome"]


def normalize_playwright_channel(value: str | None) -> PlaywrightBrowserChannel:
    normalized = (value or "chromium").strip().lower()
    return "chrome" if normalized == "chrome" else "chromium"


def chromium_launch_channel_kwargs(channel: PlaywrightBrowserChannel) -> dict[str, Any]:
    """Extra kwargs for ``playwright.chromium.launch`` when using branded Chrome."""
    if channel == "chrome":
        return {"channel": "chrome"}
    return {}
