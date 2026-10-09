"""When cloud backends fail, offer operator-confirmed switch to local Wan."""
from __future__ import annotations

import time

from app.config import Settings, get_settings
from app.db.models import GenerationJob, PipelineStatus

LOCAL_SWITCH_OFFER_MARKER = "LOCAL_SWITCH_OFFER:"

_WAN_HEALTH_CACHE: tuple[float, bool] | None = None
_WAN_HEALTH_TTL_S = 60.0


def skip_local_in_auto_chain(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if not settings.local_render_requires_confirm:
        return False
    return bool((settings.wan_base_url or "").strip())


def _local_wan_available_uncached(settings: Settings) -> bool:
    from app.generation.registry import get_backend

    if not (settings.wan_base_url or "").strip():
        return False
    try:
        engine = get_backend("local", settings)
    except NotImplementedError:
        return False
    return engine.healthcheck()


def local_wan_available(settings: Settings | None = None) -> bool:
    global _WAN_HEALTH_CACHE
    settings = settings or get_settings()
    now = time.monotonic()
    if _WAN_HEALTH_CACHE is not None and now - _WAN_HEALTH_CACHE[0] < _WAN_HEALTH_TTL_S:
        return _WAN_HEALTH_CACHE[1]
    ok = _local_wan_available_uncached(settings)
    _WAN_HEALTH_CACHE = (now, ok)
    return ok


def should_offer_local_switch(job: GenerationJob, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if job.status not in (PipelineStatus.failed, PipelineStatus.dead):
        return False
    backend = (job.backend or "").strip().lower()
    if backend in {"local", "slideshow"}:
        return False
    if not local_wan_available(settings):
        return False
    err = job.last_error or ""
    return LOCAL_SWITCH_OFFER_MARKER in err
