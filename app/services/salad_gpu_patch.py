"""Serve and install Wan generate_server.py on Salad without rebuilding the GPU image."""
from __future__ import annotations

import shlex
from pathlib import Path
from urllib.parse import quote

from app.config import Settings, get_settings

WAN_ASYNC_PATCH_MARKER = "wan-async-patch"


def generate_server_source_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    return root / "docker" / "salad-gpu" / "generate_server.py"


def patch_configured(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    base = (settings.salad_gpu_patch_public_base or "").strip()
    token = (settings.salad_gpu_patch_token or "").strip()
    wan = (settings.wan_base_url or "").strip()
    return bool(base and token and wan)


def patch_download_url(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    base = (settings.salad_gpu_patch_public_base or "").strip().rstrip("/")
    token = (settings.salad_gpu_patch_token or "").strip()
    if not base or not token:
        return ""
    return f"{base}/api/salad-gpu/generate_server.py?token={quote(token, safe='')}"


def patch_curl_shell(settings: Settings | None = None) -> str:
    url = patch_download_url(settings)
    if not url or not patch_configured(settings):
        return ""
    return f"curl -fsSL {shlex.quote(url)} -o /opt/gpu/generate_server.py"
