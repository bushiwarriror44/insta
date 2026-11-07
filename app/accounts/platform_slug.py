"""Normalize DB/API platform values to slug strings (youtube, tiktok, instagram)."""
from __future__ import annotations

from typing import Any


def normalize_platform_slug(platform: Any) -> str:
    if platform is None:
        return "instagram"
    value = getattr(platform, "value", None)
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    if isinstance(platform, str):
        raw = platform.strip()
        if not raw:
            return "instagram"
        if raw.startswith("Platform."):
            return raw.split(".", 1)[1].strip().lower()
        return raw.lower()
    name = getattr(platform, "name", None)
    if isinstance(name, str) and name.strip():
        return name.strip().lower()
    text = str(platform).strip()
    if text.startswith("Platform."):
        return text.split(".", 1)[1].strip().lower()
    return text.lower() or "instagram"
