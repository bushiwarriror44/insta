"""One short-lived probe shared by the GPU card, connection menu, and render backends."""
from __future__ import annotations

import threading
import time

import httpx

from app.config import Settings
from app.services.http import client as http_client
from app.services.runtime import native

PROBE_TTL_S = 20.0
ASYNC_PROBE_TTL_S = 120.0

_lock = threading.Lock()
_wan: dict[str, tuple[float, bool]] = {}
_wan_async: dict[str, tuple[float, bool]] = {}
_chat: dict[str, tuple[float, bool]] = {}


def clear_probes() -> None:
    with _lock:
        _wan.clear()
        _wan_async.clear()
        _chat.clear()


def _cached(
    store: dict[str, tuple[float, bool]], key: str, ttl: float
) -> bool | None:
    now = time.monotonic()
    with _lock:
        hit = store.get(key)
        if hit is not None and now - hit[0] < ttl:
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
    cached = _cached(_wan, url, PROBE_TTL_S)
    if cached is not None:
        return cached
    try:
        with http_client(settings, timeout=3.0) as client:
            response = client.get(url)
    except httpx.RequestError:
        return _store(_wan, url, False)
    ok = 200 <= response.status_code < 300 or response.status_code == 405
    return _store(_wan, url, ok)


def wan_async_capable(settings: Settings) -> bool | None:
    """Salad hosts must answer async submit (202/409/400), not a blocking mp4 (200).

    None when WAN is unset or the URL is not a public Salad gateway (direct GPU may sync).
    """
    url = (settings.wan_base_url or "").strip()
    if not url:
        return None
    if "salad.cloud" not in url.lower() and not settings.wan_async:
        return None
    cached = _cached(_wan_async, url, ASYNC_PROBE_TTL_S)
    if cached is not None:
        return cached
    if wan_reachable(settings) is not True:
        return _store(_wan_async, url, False)
    base = url.rstrip("/")
    post_url = base if base.endswith("/generate") else f"{base}/generate"
    try:
        with http_client(settings, timeout=15.0) as client:
            response = client.post(
                post_url,
                json={"prompt": "", "duration_s": 5},
                headers={"Content-Type": "application/json", "X-Async": "1"},
            )
    except httpx.RequestError:
        return _store(_wan_async, url, False)
    if response.status_code in {202, 409, 400}:
        return _store(_wan_async, url, True)
    if response.status_code == 200:
        ctype = (response.headers.get("content-type") or "").lower()
        if "json" in ctype:
            try:
                body = response.json()
            except ValueError:
                body = None
            if isinstance(body, dict) and body.get("job_id"):
                return _store(_wan_async, url, True)
        return _store(_wan_async, url, False)
    return _store(_wan_async, url, False)


def ollama_reachable(settings: Settings) -> bool:
    root = native(settings.agent_base_url)
    if not root:
        return False
    cached = _cached(_chat, root, PROBE_TTL_S)
    if cached is not None:
        return cached
    try:
        with http_client(settings, timeout=3.0) as client:
            response = client.get(f"{root}/api/tags")
    except httpx.RequestError:
        return _store(_chat, root, False)
    return _store(_chat, root, response.status_code < 400)
