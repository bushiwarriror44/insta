"""One short-lived probe shared by the GPU card, connection menu, and render backends."""
from __future__ import annotations

import threading
import time

import httpx

from app.config import Settings
from app.services.http import client as http_client
from app.services.runtime import native

PROBE_TTL_S = 20.0

_lock = threading.Lock()
_wan: dict[str, tuple[float, bool]] = {}
_chat: dict[str, tuple[float, bool]] = {}


def clear_probes() -> None:
    with _lock:
        _wan.clear()
        _chat.clear()


def _cached(store: dict[str, tuple[float, bool]], key: str) -> bool | None:
    now = time.monotonic()
    with _lock:
        hit = store.get(key)
        if hit is not None and now - hit[0] < PROBE_TTL_S:
            return hit[1]
    return None


def _store(store: dict[str, tuple[float, bool]], key: str, ok: bool) -> bool:
    with _lock:
        store[key] = (time.monotonic(), ok)
    return ok


def wan_reachable(settings: Settings) -> bool | None:
    """None when WAN_BASE_URL is empty. 2xx or 405 means the generate route is up."""
    url = (settings.wan_base_url or "").strip()
    if not url:
        return None
    cached = _cached(_wan, url)
    if cached is not None:
        return cached
    try:
        with http_client(settings, timeout=3.0) as client:
            response = client.get(url)
    except httpx.RequestError:
        return _store(_wan, url, False)
    ok = 200 <= response.status_code < 300 or response.status_code == 405
    return _store(_wan, url, ok)


def ollama_reachable(settings: Settings) -> bool:
    root = native(settings.agent_base_url)
    if not root:
        return False
    cached = _cached(_chat, root)
    if cached is not None:
        return cached
    try:
        with http_client(settings, timeout=3.0) as client:
            response = client.get(f"{root}/api/tags")
    except httpx.RequestError:
        return _store(_chat, root, False)
    return _store(_chat, root, response.status_code < 400)
