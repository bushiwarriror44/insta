"""Shared Wan / worker timeout math (keep in sync with salad-gpu generate_server)."""

from __future__ import annotations

from app.config import Settings
from app.db.models import GenerationJob

# docker/salad-gpu/generate_server.py WAN_TIMEOUT_S
WAN_GPU_SUBPROCESS_TIMEOUT_S = 1800.0
WAN_WORKER_BUFFER_S = 120.0


def salad_wan_host(settings: Settings) -> bool:
    return "salad.cloud" in (settings.wan_base_url or "").lower()


def effective_generation_timeout(settings: Settings) -> float:
    """Worker poll limit: at least Wan subprocess + buffer on Salad gateways."""
    base = float(settings.generation_timeout_seconds)
    if salad_wan_host(settings):
        floor = WAN_GPU_SUBPROCESS_TIMEOUT_S + WAN_WORKER_BUFFER_S
        return max(base, floor)
    return base


def longform_wall_timeout(settings: Settings) -> float:
    return effective_generation_timeout(settings) * 1.2


def wait_render_timeout_s(settings: Settings, job: GenerationJob) -> float:
    backend = (job.backend or "").strip().lower()
    stage = (job.stage or "").lower()
    wan_path = bool((settings.wan_base_url or "").strip())
    if backend == "local":
        return effective_generation_timeout(settings) + WAN_WORKER_BUFFER_S
    if backend == "auto" and wan_path:
        return effective_generation_timeout(settings) + WAN_WORKER_BUFFER_S
    if "wan" in stage or "сегмент" in stage:
        return effective_generation_timeout(settings) + WAN_WORKER_BUFFER_S
    return 900.0
