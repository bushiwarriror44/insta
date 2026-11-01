from app.config import Settings
from app.generation.wan_limits import (
    WAN_GPU_SUBPROCESS_TIMEOUT_S,
    WAN_WORKER_BUFFER_S,
    effective_generation_timeout,
    salad_wan_host,
)


def test_salad_floor_timeout():
    settings = Settings(
        _env_file=None,
        wan_base_url="https://x.salad.cloud/generate",
        generation_timeout_seconds=900,
    )
    assert salad_wan_host(settings)
    assert effective_generation_timeout(settings) == WAN_GPU_SUBPROCESS_TIMEOUT_S + WAN_WORKER_BUFFER_S


def test_direct_host_uses_configured_timeout():
    settings = Settings(
        _env_file=None,
        wan_base_url="https://gpu.internal/generate",
        generation_timeout_seconds=900,
    )
    assert effective_generation_timeout(settings) == 900.0
