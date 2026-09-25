"""Owner-only Start/Stop for the Salad GPU container group."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException

from app.api.deps import DocsOwnerDep
from app.api.schemas import GpuOut
from app.config import Settings, get_settings
from app.services import salad_gpu
from app.services.http import client as http_client
from app.services.runtime import native

router = APIRouter(prefix="/api/gpu", tags=["gpu"], dependencies=[DocsOwnerDep])

# Group is down — probes must not claim Ollama/Wan are live.
_DOWN = frozenset({"stopped", "succeeded", "failed"})


def _wan_ok(settings: Settings) -> bool | None:
    url = (settings.wan_base_url or "").strip()
    if not url:
        return None
    try:
        with http_client(settings, timeout=3.0) as client:
            response = client.get(url)
    except httpx.RequestError:
        return False
    # 2xx = health; 405 = POST-only /generate is up. 404 from Salad edge ≠ live Wan.
    return 200 <= response.status_code < 300 or response.status_code == 405


def _chat_ok(settings: Settings) -> bool:
    root = native(settings.agent_base_url)
    if not root:
        return False
    try:
        with http_client(settings, timeout=3.0) as client:
            response = client.get(f"{root}/api/tags")
    except httpx.RequestError:
        return False
    return response.status_code < 400


def _payload(state: salad_gpu.GroupState | None, settings: Settings) -> GpuOut:
    ready = salad_gpu.configured(settings)
    if state is None:
        return GpuOut(
            configured=ready,
            detail="" if ready else "Задайте SALAD_API_KEY и имена группы в .env",
            wan_ok=_wan_ok(settings),
            idle_stop_minutes=int(settings.salad_idle_stop_minutes),
        )
    chat_ok = _chat_ok(settings)
    wan_ok = _wan_ok(settings)
    if state.status in _DOWN:
        chat_ok = False
        if wan_ok is not None:
            wan_ok = False
    return GpuOut(
        configured=True,
        status=state.status,
        billing=state.billing,
        allocating_count=state.allocating_count,
        creating_count=state.creating_count,
        running_count=state.running_count,
        stopping_count=state.stopping_count,
        chat_ok=chat_ok,
        wan_ok=wan_ok,
        detail=state.detail,
        idle_stop_minutes=int(settings.salad_idle_stop_minutes),
    )


def _http_error(exc: salad_gpu.SaladProblem) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("", response_model=GpuOut)
def read_gpu() -> GpuOut:
    settings = get_settings()
    if not salad_gpu.configured(settings):
        return _payload(None, settings)
    try:
        return _payload(salad_gpu.get_group(settings), settings)
    except salad_gpu.SaladProblem as exc:
        # Keep probes fresh so the Connection menu does not stick on a stale snapshot.
        return GpuOut(
            configured=True,
            detail=str(exc),
            chat_ok=_chat_ok(settings),
            wan_ok=_wan_ok(settings),
            idle_stop_minutes=int(settings.salad_idle_stop_minutes),
        )


@router.post("/start", response_model=GpuOut)
def start_gpu() -> GpuOut:
    settings = get_settings()
    try:
        return _payload(salad_gpu.start_group(settings), settings)
    except salad_gpu.SaladProblem as exc:
        raise _http_error(exc) from exc


@router.post("/stop", response_model=GpuOut)
def stop_gpu() -> GpuOut:
    settings = get_settings()
    try:
        return _payload(salad_gpu.stop_group(settings), settings)
    except salad_gpu.SaladProblem as exc:
        raise _http_error(exc) from exc
