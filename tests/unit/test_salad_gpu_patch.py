"""HTTP patch of generate_server.py for Salad without rebuilding the GPU image."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.services.salad_gpu import warmup_script
from app.services.salad_gpu_patch import (
    WAN_ASYNC_PATCH_MARKER,
    generate_server_source_path,
    patch_configured,
    patch_curl_shell,
    patch_download_url,
)


def test_patch_url_requires_base_token_and_wan(monkeypatch):
    monkeypatch.setattr(settings, "salad_gpu_patch_public_base", "http://203.0.113.10:8000")
    monkeypatch.setattr(settings, "salad_gpu_patch_token", "secret-token")
    monkeypatch.setattr(settings, "wan_base_url", "https://host.salad.cloud/generate")
    assert patch_configured(settings)
    url = patch_download_url(settings)
    assert url.startswith("http://203.0.113.10:8000/api/salad-gpu/generate_server.py?token=")
    curl = patch_curl_shell(settings)
    assert "curl --connect-timeout 10 --max-time 45 -fsSL" in curl
    assert "/opt/gpu/generate_server.py" in curl
    assert "|| echo" in curl


def test_warmup_includes_curl_when_patch_configured(monkeypatch):
    monkeypatch.setattr(settings, "salad_gpu_patch_public_base", "http://203.0.113.10:8000")
    monkeypatch.setattr(settings, "salad_gpu_patch_token", "secret-token")
    monkeypatch.setattr(settings, "wan_base_url", "https://host.salad.cloud/generate")
    script = warmup_script("qwen3:32b", settings)
    assert WAN_ASYNC_PATCH_MARKER in script
    assert "--max-time 45" in script
    assert 'wait "$pip_pid" || true' in script
    assert script.index("pip install") < script.index("curl --connect-timeout") < script.index("start.sh")


def test_generate_server_source_exists_in_repo():
    path = generate_server_source_path()
    assert path.is_file(), path
    text = path.read_text(encoding="utf-8")
    assert "X-Async" in text
    assert '@app.get("/generate")' in text


@pytest.fixture()
def patch_client(app_env, monkeypatch):
    from app.api import deps as api_deps
    from app.api.main import create_app

    app = create_app()

    def _override_get_db():
        db = app_env.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[api_deps.get_db] = _override_get_db
    with TestClient(app) as c:
        yield c


def test_api_serves_generate_server_with_token(patch_client, monkeypatch, tmp_path):
    src = tmp_path / "generate_server.py"
    src.write_text("# patch test\n", encoding="utf-8")
    monkeypatch.setattr(
        "app.api.routes.salad_gpu_patch.generate_server_source_path",
        lambda: src,
    )
    monkeypatch.setattr(settings, "salad_gpu_patch_token", "ok-token")
    bad = patch_client.get("/api/salad-gpu/generate_server.py", params={"token": "nope"})
    assert bad.status_code == 404
    good = patch_client.get("/api/salad-gpu/generate_server.py", params={"token": "ok-token"})
    assert good.status_code == 200
    assert good.text.startswith("# patch test")
