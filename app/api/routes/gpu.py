"""Owner-only Start/Stop for the Salad GPU container group."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response

from app.api.deps import AuthDep, DocsOwnerDep
from app.api.schemas import GpuLogsOut, GpuOut, GpuPresenceIn, GpuPresenceOut, LogTailOut
from app.config import Settings, get_settings
from app.services import salad_gpu, salad_idle
from app.services.gateway_probe import ollama_reachable, wan_reachable

router = APIRouter(prefix="/api/gpu", tags=["gpu"])

# Group is down — probes must not claim Ollama/Wan are live.
_DOWN = frozenset({"stopped", "succeeded", "failed"})


def _wan_ok(settings: Settings) -> bool | None:
    return wan_reachable(settings)


def _chat_ok(settings: Settings) -> bool:
    return ollama_reachable(settings)


def _counts(state: salad_gpu.GroupState) -> str:
    return (
        f"работают {state.running_count}, создаются {state.creating_count}, "
        f"выделяются {state.allocating_count}"
    )


def _elapsed_label(started: datetime | None) -> str:
    if started is None:
        return ""
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    total = max(0, int((datetime.now(timezone.utc) - started).total_seconds()))
    if total < 60:
        return f"{total} с"
    return f"{total // 60} мин {total % 60:02d} с"


def _connect(
    state: salad_gpu.GroupState | None,
    *,
    chat_ok: bool,
    started: datetime | None,
    settings: Settings | None = None,
) -> tuple[Literal["idle", "pull", "boot", "gateway", "ready"], str, str, float]:
    """One shared connect stage. HTTP 200 from Salad is not success."""
    if state is None or state.status in _DOWN or not state.status:
        return "idle", "", "", 0.0
    counts = _counts(state)
    replica_up = state.status == "running" or state.replica_ready
    if chat_ok and replica_up:
        return "ready", "Чат отвечает", counts, 1.0
    if replica_up:
        return "gateway", "Узел запущен, жду Ollama", "шлюз не отвечает", 0.8
    restart = salad_gpu.pull_restart_note_active(settings)
    if state.status == "deploying" or state.creating_count > 0:
        clock = _elapsed_label(started)
        detail = f"{clock} · {counts}" if clock else counts
        label = (
            salad_gpu.PHASE_PULL_RESTART if restart else "Качается образ на узел"
        )
        return "pull", label, detail, 0.45
    if state.allocating_count > 0:
        label = salad_gpu.PHASE_PULL_RESTART if restart else "Выделяю GPU"
        return "boot", label, counts, 0.6
    if state.status == "pending":
        return "boot", "Жду узел", counts, 0.2
    return "boot", f"Запуск ({state.status})", counts, 0.3


def _payload(state: salad_gpu.GroupState | None, settings: Settings) -> GpuOut:
    ready = salad_gpu.configured(settings)
    if state is None:
        detail = "" if ready else "Задайте SALAD_API_KEY и имена группы в .env"
        return GpuOut(
            configured=ready,
            detail=detail,
            wan_ok=_wan_ok(settings),
            idle_stop_minutes=int(settings.salad_idle_stop_minutes),
        )
    booting = (
        state.status in {"pending", "deploying"}
        or state.creating_count > 0
        or state.allocating_count > 0
    )
    forced_down = state.status in _DOWN
    if forced_down or booting:
        chat_ok = False
        wan_ok = None if not (settings.wan_base_url or "").strip() else False
    else:
        chat_ok = _chat_ok(settings)
        wan_ok = _wan_ok(settings)
    started = salad_gpu.pull_started_at(state, settings)
    phase, label, connect_detail, ratio = _connect(
        state, chat_ok=chat_ok, started=started, settings=settings
    )
    detail = state.detail
    if salad_gpu.pull_restart_note_active(settings) and state.still_pulling:
        detail = salad_gpu.PHASE_PULL_RESTART
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
        detail=detail,
        idle_stop_minutes=int(settings.salad_idle_stop_minutes),
        deploy_started_at=started,
        connect_phase=phase,
        connect_label=label,
        connect_detail=connect_detail,
        connect_ratio=ratio,
    )


def _http_error(exc: salad_gpu.SaladProblem) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


_LOG_SERVICES = ("reels-api", "reels-worker", "reels-frontend")
_LOG_WINDOWS = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
}
_LOG_EMPTY = {
    "15m": "за последние 15 минут логов нет",
    "1h": "за последний час логов нет",
    "6h": "за последние 6 часов логов нет",
    "24h": "за последние 24 часа логов нет",
}


def _hide_key(settings: Settings, text: str) -> str:
    key = settings.salad_api_key.strip()
    if len(key) >= 8 and key in text:
        return text.replace(key, "…")
    return text


def _tail(name: str, row: Mapping[str, object], settings: Settings) -> LogTailOut:
    raw_lines = row.get("lines")
    lines = [_hide_key(settings, str(line)) for line in raw_lines] if isinstance(raw_lines, list) else []
    return LogTailOut(
        name=name,
        available=bool(row.get("available")),
        reason=_hide_key(settings, str(row.get("reason") or "")),
        lines=lines,
    )


@router.post("/presence", response_model=GpuPresenceOut, dependencies=[AuthDep])
def post_gpu_presence(payload: GpuPresenceIn) -> GpuPresenceOut:
    """Keep Salad GPU awake while any panel tab is open (multi-client)."""
    try:
        viewers = salad_idle.touch_presence(payload.client_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GpuPresenceOut(ok=True, viewers=viewers)


@router.get("/logs", response_model=GpuLogsOut, dependencies=[DocsOwnerDep])
def read_gpu_logs(response: Response, since: str = Query(default="1h")) -> GpuLogsOut:
    """Docker tails plus Salad container stdout. Does not refresh the idle clock."""
    from app.assistant.tools import docker_logs

    response.headers["Cache-Control"] = "no-store"
    window = since if since in _LOG_WINDOWS else "1h"
    settings = get_settings()
    docker = [
        _tail(name, docker_logs(name, tail=200, since=window), settings) for name in _LOG_SERVICES
    ]
    gpu = salad_gpu.container_logs(
        settings,
        since=_LOG_WINDOWS[window],
        empty_reason=_LOG_EMPTY[window],
    )
    return GpuLogsOut(docker=docker, gpu=_tail("gpu", gpu, settings))


@router.get("", response_model=GpuOut, dependencies=[DocsOwnerDep])
def read_gpu() -> GpuOut:
    settings = get_settings()
    if not salad_gpu.configured(settings):
        return _payload(None, settings)
    try:
        return _payload(salad_gpu.get_group(settings), settings)
    except salad_gpu.SaladProblem as exc:
        # Keep probes fresh so the Connection menu does not stick on a stale snapshot.
        chat_ok = _chat_ok(settings)
        wan_ok = _wan_ok(settings)
        return GpuOut(
            configured=True,
            detail=str(exc),
            chat_ok=chat_ok,
            wan_ok=wan_ok,
            idle_stop_minutes=int(settings.salad_idle_stop_minutes),
        )


@router.post("/start", response_model=GpuOut, dependencies=[DocsOwnerDep])
def start_gpu() -> GpuOut:
    settings = get_settings()
    try:
        state = salad_gpu.start_group(settings)
        return _payload(state, settings)
    except salad_gpu.SaladProblem as exc:
        raise _http_error(exc) from exc


@router.post("/stop", response_model=GpuOut, dependencies=[DocsOwnerDep])
def stop_gpu() -> GpuOut:
    settings = get_settings()
    try:
        state = salad_gpu.stop_group(settings)
        return _payload(state, settings)
    except salad_gpu.SaladProblem as exc:
        raise _http_error(exc) from exc
