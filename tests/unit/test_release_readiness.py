"""Release gate anchors: compose layout, handbook release semantics."""
from __future__ import annotations

from pathlib import Path

import yaml

from app.assistant.chat import HANDBOOK_PATH

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"


def test_docker_compose_release_services_and_shared_data():
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    services = data["services"]
    for name in ("reels-api", "reels-worker", "reels-frontend"):
        assert name in services

    api_mounts = services["reels-api"].get("volumes") or []
    worker_mounts = services["reels-worker"].get("volumes") or []
    assert "./data:/app/data" in api_mounts
    assert "./data:/app/data" in worker_mounts

    api_hc = services["reels-api"].get("healthcheck", {}).get("test", [])
    worker_hc = services["reels-worker"].get("healthcheck", {}).get("test", [])
    assert any("api/health" in str(part) for part in api_hc)
    assert any("status" in str(part) for part in worker_hc)
    assert services["reels-frontend"].get("ports") == ["3000:80"]
    nginx = (ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    frontend_dockerfile = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    assert "/healthz" in nginx
    assert "healthz" in frontend_dockerfile


def test_handbook_release_bundle_hold_and_preview():
    text = HANDBOOK_PATH.read_text(encoding="utf-8")
    assert "hold_for_review" in text
    assert "awaiting_review" in text
    assert "preview_plan" in text
    assert "воркер" in text.lower() or "воркер для" in text.lower()
    preview_chunk = text.split("preview_plan", 1)[1][:800]
    assert "dry-run" not in preview_chunk.lower() and "dry run" not in preview_chunk.lower()
