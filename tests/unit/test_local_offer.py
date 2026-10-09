from types import SimpleNamespace

from app.config import Settings
from app.db.models import GenerationJob, PipelineStatus
import app.generation.local_offer as local_offer
from app.generation.local_offer import (
    LOCAL_SWITCH_OFFER_MARKER,
    local_wan_available,
    should_offer_local_switch,
    skip_local_in_auto_chain,
)


def test_skip_local_in_auto_chain_requires_wan():
    assert skip_local_in_auto_chain(Settings()) is False
    assert skip_local_in_auto_chain(Settings(wan_base_url="http://wan", local_render_requires_confirm=True))


def test_should_offer_local_switch_on_marker(monkeypatch):
    settings = Settings(wan_base_url="http://wan/generate")
    job = GenerationJob(
        prompt="x",
        backend="auto",
        status=PipelineStatus.failed,
        last_error=f"{LOCAL_SWITCH_OFFER_MARKER} fal: down",
    )
    monkeypatch.setattr(
        "app.generation.registry.get_backend",
        lambda *_a, **_k: SimpleNamespace(healthcheck=lambda: True),
    )
    assert should_offer_local_switch(job, settings) is True


def test_should_not_offer_cloud_fail_without_marker(monkeypatch):
    settings = Settings(wan_base_url="http://wan/generate")
    job = GenerationJob(
        prompt="x",
        backend="fal",
        status=PipelineStatus.failed,
        last_error="invalid api key",
    )
    monkeypatch.setattr(
        "app.generation.registry.get_backend",
        lambda *_a, **_k: SimpleNamespace(healthcheck=lambda: True),
    )
    assert should_offer_local_switch(job, settings) is False


def test_should_not_offer_for_local_backend(monkeypatch):
    settings = Settings(wan_base_url="http://wan/generate")
    job = GenerationJob(
        prompt="x",
        backend="local",
        status=PipelineStatus.failed,
        last_error="fail",
    )
    monkeypatch.setattr(
        "app.generation.registry.get_backend",
        lambda *_a, **_k: SimpleNamespace(healthcheck=lambda: True),
    )
    assert should_offer_local_switch(job, settings) is False


def test_local_wan_healthcheck_cached(monkeypatch):
    local_offer._WAN_HEALTH_CACHE = None
    settings = Settings(wan_base_url="http://wan/generate")
    calls = {"n": 0}

    def fake_uncached(_settings):
        calls["n"] += 1
        return True

    monkeypatch.setattr(local_offer, "_local_wan_available_uncached", fake_uncached)
    assert local_wan_available(settings) is True
    assert local_wan_available(settings) is True
    assert calls["n"] == 1
