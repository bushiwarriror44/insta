"""Best-effort cancel of in-flight Wan jobs on the GPU host."""

from __future__ import annotations

import json
import logging

from app.config import Settings, get_settings
from app.services.gpu_slot import lock_path
from app.services.http import client as http_client

log = logging.getLogger(__name__)


def generate_jobs_base(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    url = (settings.wan_base_url or "").strip().rstrip("/")
    if not url:
        return ""
    if url.endswith("/generate"):
        return url
    return f"{url}/generate"


def note_remote_wan_job(settings: Settings | None, remote_job_id: str) -> None:
    settings = settings or get_settings()
    rid = (remote_job_id or "").strip()
    if not rid:
        return
    path = lock_path(settings)
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    data["remote_job_id"] = rid
    try:
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def read_remote_wan_job(settings: Settings | None = None) -> str | None:
    settings = settings or get_settings()
    path = lock_path(settings)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rid = str(data.get("remote_job_id") or "").strip()
    return rid or None


def best_effort_cancel_wan(
    settings: Settings | None,
    remote_job_id: str | None = None,
) -> None:
    settings = settings or get_settings()
    rid = (remote_job_id or read_remote_wan_job(settings) or "").strip()
    base = generate_jobs_base(settings)
    if not rid or not base:
        return
    headers: dict[str, str] = {}
    if settings.wan_api_key:
        headers["Authorization"] = f"Bearer {settings.wan_api_key}"
    url = f"{base}/jobs/{rid}/cancel"
    try:
        with http_client(settings, timeout=30.0, headers=headers) as client:
            client.post(url)
    except Exception as exc:
        log.debug("wan.cancel_failed job_id=%s err=%s", rid, exc)


def local_async_required_detail(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return (
        "Локальный Wan на Salad требует async API (POST X-Async: 1 → 202). "
        "Обновите generate_server.py на GPU и сделайте Stop/Start группы Salad, "
        "либо используйте backend auto/fal."
    )
