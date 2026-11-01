from unittest.mock import MagicMock, patch

import httpx

from app.config import Settings
from app.services.gateway_probe import clear_probes, wan_async_capable, wan_reachable


def _settings(**overrides) -> Settings:
    base = {
        "wan_base_url": "https://host.salad.cloud/generate",
        "wan_async": False,
    }
    base.update(overrides)
    return Settings(**base)


def test_wan_async_capable_none_without_url():
    clear_probes()
    assert wan_async_capable(_settings(wan_base_url="")) is None


def test_wan_async_capable_none_for_direct_gpu_without_flag():
    clear_probes()
    assert (
        wan_async_capable(_settings(wan_base_url="https://gpu.internal/generate")) is None
    )


def test_wan_async_capable_true_on_202():
    clear_probes()
    settings = _settings()
    response = httpx.Response(202, json={"job_id": "abc", "status": "queued"})
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get.return_value = httpx.Response(200, json={"ok": True})
    client.post.return_value = response
    with patch("app.services.gateway_probe.http_client", return_value=client):
        assert wan_async_capable(settings) is True


def test_wan_async_capable_true_on_empty_prompt_400():
    clear_probes()
    settings = _settings()
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get.return_value = httpx.Response(200, json={"ok": True})
    client.post.return_value = httpx.Response(400, json={"detail": "prompt is empty"})
    with patch("app.services.gateway_probe.http_client", return_value=client):
        assert wan_async_capable(settings) is True


def test_wan_async_capable_false_on_sync_mp4_200():
    clear_probes()
    settings = _settings()
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get.return_value = httpx.Response(200, json={"ok": True})
    client.post.return_value = httpx.Response(
        200,
        headers={"content-type": "video/mp4"},
        content=b"\x00",
    )
    with patch("app.services.gateway_probe.http_client", return_value=client):
        assert wan_async_capable(settings) is False


def test_wan_reachable_caches():
    clear_probes()
    settings = _settings()
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get.return_value = httpx.Response(200, json={"ok": True})
    with patch("app.services.gateway_probe.http_client", return_value=client):
        assert wan_reachable(settings) is True
        assert wan_reachable(settings) is True
    assert client.get.call_count == 1
