"""Salad Cloud container-group Start/Stop for the admin panel.

The panel talks to the Salad Public API so the owner does not need the
Salad portal for day-to-day GPU hours. Running bills; Stop does not.
Start after Stop pulls the image onto a node again.

The API key never leaves this module in logs or raised messages.
"""

from __future__ import annotations

import json
import re
import time
from contextvars import ContextVar
from collections.abc import Callable, Generator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from app.config import Settings, get_settings
from app.services.salad_gpu_patch import (
    WAN_ASYNC_PATCH_MARKER,
    patch_configured,
    patch_curl_shell,
)
from app.logging_setup import get_logger
from app.services.http import client as http_client

log = get_logger(__name__)

SALAD_API_ROOT = "https://api.salad.com/api/public"
TIMEOUT = 30.0

START_READY = frozenset({"stopped", "succeeded", "failed"})
STOP_READY = frozenset({"running", "pending", "deploying"})
GATEWAY_PORT = 11434
WAN_GATEWAY_PORT = 8080
WARMUP_MARKER = "gpu-warmup"
IPV6_MARKER = "gateway-ipv6"
WAN_DEPS_MARKER = "wan-dashscope"
WAN_SDPA_MARKER = "wan-sdpa-attn"
SEND_START = "Отправляю Start в Salad…"
LAUNCH_STATUS = "Запускаю видеокарту, подождите"
START_NOT_SENT = "Не удалось отправить Start в Salad, группа осталась остановленной."
API_DOWN = "API Salad не отвечает. Напишите снова через минуту."
WARM_STATUS = "Прогреваю модель, подождите"
PHASE_PATCH = "Настраиваю шлюз"
PHASE_NODE = "Жду узел"
PHASE_PULL = "Качается образ на узел"
PHASE_PULL_RESTART = "Узел Salad offline — качаю образ заново"
PHASE_ALLOC = "Выделяю GPU"
PHASE_OLLAMA = "Жду Ollama"
PHASE_MODEL = "Гружу модель в память"
PHASE_API = "Связь с Salad, повтор…"
SALAD_UNREACHABLE = "Salad не отвечает"
API_DOWN_WHILE_PULL = (
    "API Salad не отвечает, но группа может ещё качать образ — "
    "проверьте портал и напишите снова через минуту"
)
POLL_TIMEOUT = 8.0
_poll_timeout: ContextVar[float | None] = ContextVar("salad_poll_timeout", default=None)
POLL_API_ATTEMPTS = 5
ACTION_API_ATTEMPTS = 3
POLL_S = 5.0
START_WAIT_S = 25 * 60
PULL_WAIT_S = 90 * 60
WARM_WAIT_S = 20 * 60
KICK_TIMEOUT_S = 20.0
KICK_INTERVAL_S = 30.0
PULL_RESTART_NOTE_S = 15 * 60
NODE_OFFLINE_PROBE_S = 60.0
PREP_PHASES = 4
_MODEL_NAME = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
_node_offline_probe: tuple[float, bool] = (0.0, False)


class SaladProblem(Exception):
    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class WireTrace:
    """One Salad or Ollama call shown in the chat. Never includes the API key."""

    method: str
    path: str
    result: str


@dataclass(frozen=True)
class PrepStatus:
    """Live line for the chat dock while Salad starts and the model loads."""

    title: str
    phase: int
    phases: int = PREP_PHASES
    ratio: float = 0.0
    detail: str = ""
    milestone: bool = False

    @property
    def text(self) -> str:
        if self.detail:
            return f"{self.title} · {self.detail}"
        return self.title


@dataclass(frozen=True)
class GroupState:
    status: str
    allocating_count: int = 0
    creating_count: int = 0
    running_count: int = 0
    stopping_count: int = 0
    detail: str = ""
    dns: str = ""
    port: int = 0
    command: tuple[str, ...] = ()
    start_time: datetime | None = None

    @property
    def billing(self) -> bool:
        return self.status == "running"

    @property
    def replica_ready(self) -> bool:
        """Portal can still say deploying while the replica is already running."""
        return self.running_count > 0 and self.creating_count == 0

    @property
    def still_pulling(self) -> bool:
        if self.replica_ready:
            return False
        return self.status in {"pending", "deploying"} or self.creating_count > 0


def configured(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(
        settings.salad_api_key.strip()
        and settings.salad_organization.strip()
        and settings.salad_project.strip()
        and settings.salad_container_group.strip()
    )


def _names(settings: Settings) -> tuple[str, str, str]:
    return (
        settings.salad_organization.strip(),
        settings.salad_project.strip(),
        settings.salad_container_group.strip(),
    )


def _group_public_path(settings: Settings) -> str:
    org, project, group = _names(settings)
    return f"/organizations/{org}/projects/{project}/containers/{group}"


def _group_url(settings: Settings) -> str:
    org, project, group = _names(settings)
    return (
        f"{SALAD_API_ROOT}/organizations/{quote(org, safe='')}"
        f"/projects/{quote(project, safe='')}"
        f"/containers/{quote(group, safe='')}"
    )


def _headers(settings: Settings) -> dict[str, str]:
    return {
        "Salad-Api-Key": settings.salad_api_key.strip(),
        "Accept": "application/json",
    }


def _safe_detail(status_code: int, payload: Any) -> str:
    if status_code == 400:
        return "Salad отклонил запрос"
    if status_code == 403:
        return "Salad отказал в доступе"
    if status_code == 404:
        return "Группа Salad не найдена"
    if status_code == 429:
        return "Salad лимит запросов, позже"
    if status_code == 415:
        return "Salad отклонил формат запроса."
    if isinstance(payload, dict):
        for key in ("message", "title", "detail", "error"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip() and len(value) < 240:
                return value.strip()
    return f"Salad ответил {status_code}"


def _raise_http(response: httpx.Response) -> None:
    payload: Any
    try:
        payload = response.json()
    except ValueError:
        payload = None
    status = response.status_code
    mapped = 502
    if status in {400, 403, 404, 429}:
        mapped = status
    raise SaladProblem(_safe_detail(status, payload), status_code=mapped)


def _parse_state(payload: dict[str, Any]) -> GroupState:
    state = payload.get("current_state")
    if not isinstance(state, dict):
        state = {}
    counts = state.get("instance_status_counts")
    if not isinstance(counts, dict):
        counts = {}
    status = str(state.get("status") or "").strip().lower()
    if not status:
        raise SaladProblem("Salad не вернул статус группы")
    networking = payload.get("networking")
    if not isinstance(networking, dict):
        networking = {}
    container = payload.get("container")
    if not isinstance(container, dict):
        container = {}
    raw_command = container.get("command") or []
    if isinstance(raw_command, str):
        raw_command = [raw_command]
    if not isinstance(raw_command, list):
        raw_command = []
    try:
        port = int(networking.get("port") or 0)
    except (TypeError, ValueError):
        port = 0
    return GroupState(
        status=status,
        allocating_count=int(counts.get("allocating_count") or 0),
        creating_count=int(counts.get("creating_count") or 0),
        running_count=int(counts.get("running_count") or 0),
        stopping_count=int(counts.get("stopping_count") or 0),
        detail=str(state.get("description") or "").strip()[:240],
        dns=str(networking.get("dns") or "").strip(),
        port=port,
        command=tuple(str(part) for part in raw_command if str(part).strip()),
        start_time=_parse_time(state.get("start_time")),
    )


def gateway_origin(dns: str) -> str:
    raw = dns.strip().rstrip("/")
    if not raw:
        return ""
    if "://" in raw:
        return raw
    return f"https://{raw}"


def chat_base_url(state: GroupState) -> str:
    origin = gateway_origin(state.dns)
    if not origin:
        return ""
    return origin if origin.endswith("/v1") else f"{origin}/v1"


def _model_name(settings: Settings) -> str:
    name = (settings.agent_model or "qwen3:32b").strip()
    if not _MODEL_NAME.fullmatch(name):
        return "qwen3:32b"
    return name


def _warmup_command_stale(settings: Settings, text: str) -> bool:
    if (
        WARMUP_MARKER not in text
        or IPV6_MARKER not in text
        or WAN_DEPS_MARKER not in text
        or WAN_SDPA_MARKER not in text
    ):
        return True
    if patch_configured(settings) and WAN_ASYNC_PATCH_MARKER not in text:
        return True
    return False


def _wan_sdpa_shell() -> str:
    """Point Wan model.py at attention() (SDPA) when flash-attn is missing."""
    return (
        "model=/opt/wan/wan/modules/model.py\n"
        'if [ -f "$model" ] && ! grep -q "attention as flash_attention" "$model"; then\n'
        "  sed -i 's/from \\.attention import flash_attention/"
        "from .attention import attention as flash_attention/' \"$model\"\n"
        "fi\n"
    )


def warmup_script(model: str, settings: Settings | None = None) -> str:
    """In-container warmup. The public gateway cuts requests at ~100s."""
    settings = settings or get_settings()
    curl_patch = patch_curl_shell(settings)
    header = f"# {WARMUP_MARKER} {IPV6_MARKER} {WAN_DEPS_MARKER} {WAN_SDPA_MARKER}"
    if curl_patch:
        header += f" {WAN_ASYNC_PATCH_MARKER}"
    body = json.dumps(
        {"model": model, "prompt": "hi", "stream": False, "keep_alive": "30m"}
    )
    # Single-quoted python -c; body is JSON so it has no single quotes.
    py = (
        "import urllib.request; urllib.request.urlopen(urllib.request.Request("
        '"http://127.0.0.1:11434/api/generate", data='
        + json.dumps(body)
        + '.encode(), headers={"Content-Type": "application/json"}), timeout=600).read()'
    )
    if curl_patch:
        install = (
            "python -m pip install -q dashscope &\n"
            "pip_pid=$!\n"
            f"{curl_patch}\n"
            'wait "$pip_pid" || true\n'
        )
    else:
        install = "python -m pip install -q dashscope\n"
    # Retry generate until /api/ps lists the model; tee so Salad container logs see it.
    warm_loop = (
        "(\n"
        "  i=0\n"
        '  while [ "$i" -lt 90 ]; do\n'
        "    curl -sf http://127.0.0.1:11434/ >/dev/null && break\n"
        "    i=$((i+1))\n"
        "    sleep 2\n"
        "  done\n"
        '  echo "gpu-warmup: ollama up, loading '
        + model
        + '"\n'
        "  attempt=0\n"
        '  while [ "$attempt" -lt 40 ]; do\n'
        "    if curl -sf http://127.0.0.1:11434/api/ps | grep -Fq "
        + json.dumps(model)
        + "; then\n"
        '      echo "gpu-warmup: model in memory"\n'
        "      break\n"
        "    fi\n"
        '    echo "gpu-warmup: generate attempt $attempt"\n'
        f"    python -c '{py}' || echo \"gpu-warmup: generate failed\"\n"
        "    attempt=$((attempt+1))\n"
        "    sleep 15\n"
        "  done\n"
        ") 2>&1 | tee /tmp/warmup.log &\n"
    )
    return (
        f"{header}\n"
        "set -eu\n"
        "conf=/etc/nginx/conf.d/salad.conf\n"
        "if [ -f \"$conf\" ] && ! grep -q '\\[::\\]:8080' \"$conf\"; then\n"
        "  sed -i 's/listen 8080 default_server;/listen [::]:8080 default_server ipv6only=off;/' \"$conf\"\n"
        "fi\n"
        f"{install}"
        f"{_wan_sdpa_shell()}"
        "/opt/gpu/start.sh &\n"
        "spid=$!\n"
        f"{warm_loop}"
        'wait "$spid"\n'
    )


def _command_text(state: GroupState) -> str:
    return " ".join(state.command)


def target_gateway_port(settings: Settings) -> int:
    """8080 when local Wan shares the group; 11434 for chat-only Ollama."""
    if (settings.wan_base_url or "").strip():
        return WAN_GATEWAY_PORT
    return GATEWAY_PORT


def needs_gateway_patch(settings: Settings, state: GroupState) -> bool:
    text = _command_text(state)
    if _warmup_command_stale(settings, text):
        return True
    # Salad sometimes omits networking.port. Unknown is not a mismatch.
    if state.port <= 0:
        return False
    return state.port != target_gateway_port(settings)


def patch_gateway(settings: Settings, state: GroupState) -> GroupState:
    """Install the warmup command and chat port once. Salad restarts the replica."""
    settings = require_configured(settings)
    port = target_gateway_port(settings)
    body: dict[str, Any] = {}
    text = _command_text(state)
    if _warmup_command_stale(settings, text):
        body["container"] = {
            "command": [
                "/bin/bash",
                "-c",
                warmup_script(_model_name(settings), settings),
            ]
        }
    if state.port > 0 and state.port != port:
        body["networking"] = {"port": port}
    if not body:
        return state
    url = _group_url(settings)
    log.info("salad.patch_gateway", port=port)
    try:
        with http_client(settings, timeout=TIMEOUT) as client:
            response = client.patch(
                url,
                headers={**_headers(settings), "Content-Type": "application/merge-patch+json"},
                content=json.dumps(body).encode(),
            )
    except httpx.RequestError:
        log.warning("salad.patch_failed")
        raise SaladProblem(SALAD_UNREACHABLE) from None
    if response.status_code == 415:
        log.warning("salad.patch_rejected", status=response.status_code)
        return state
    if response.status_code >= 400:
        _raise_http(response)
    return get_group(settings)


def _touch(settings: Settings) -> None:
    from app.services.salad_idle import touch

    touch(settings)


def _get(origin: str, path: str, settings: Settings) -> httpx.Response | None:
    try:
        with http_client(settings, timeout=8.0) as client:
            return client.get(f"{origin}{path}")
    except httpx.RequestError:
        return None


def _ollama_up(origin: str, settings: Settings) -> bool:
    response = _get(origin, "/", settings)
    if response is None or response.status_code >= 400:
        return False
    return "Ollama" in response.text


def _model_name_matches(name: str, model: str) -> bool:
    return name == model or name.startswith(f"{model}:")


def _models_in_payload(payload: Any) -> list[str]:
    rows = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    names: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or row.get("model") or "").strip()
        if name:
            names.append(name)
    return names


def _model_loaded(origin: str, settings: Settings, model: str) -> bool:
    response = _get(origin, "/api/ps", settings)
    if response is None or response.status_code >= 400:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    return any(_model_name_matches(name, model) for name in _models_in_payload(payload))


def _model_present(origin: str, settings: Settings, model: str) -> bool | None:
    """True/False when /api/tags answers; None when tags is unreachable."""
    response = _get(origin, "/api/tags", settings)
    if response is None or response.status_code >= 400:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    return any(_model_name_matches(name, model) for name in _models_in_payload(payload))


def _kick_model_load(origin: str, settings: Settings, model: str) -> str:
    """Ask Ollama to load the model. Short timeout: Salad gateway cuts ~100s."""
    body = {"model": model, "prompt": "hi", "stream": False, "keep_alive": "30m"}
    try:
        with http_client(settings, timeout=KICK_TIMEOUT_S) as client:
            response = client.post(f"{origin}/api/generate", json=body)
    except httpx.TimeoutException:
        return "timeout, загрузка могла начаться"
    except httpx.RequestError:
        return "нет связи"
    if response.status_code >= 400:
        return f"{response.status_code}"
    return "200, kick"


PULL_STAMP = "gpu_pull_started.txt"
PULL_TRACK = "gpu_pull_track.json"


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _utc_now(now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).replace(microsecond=0)


def _pull_path(settings: Settings) -> Path:
    return Path(settings.data_dir) / PULL_STAMP


def _track_path(settings: Settings) -> Path:
    return Path(settings.data_dir) / PULL_TRACK


def clear_pull_stamp(settings: Settings) -> None:
    try:
        _pull_path(settings).unlink(missing_ok=True)
    except OSError:
        return


def _read_pull_stamp(settings: Settings) -> datetime | None:
    try:
        text = _pull_path(settings).read_text(encoding="utf-8")
    except OSError:
        return None
    return _parse_time(text)


def _write_pull_stamp(settings: Settings, when: datetime) -> None:
    path = _pull_path(settings)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), encoding="utf-8")
    except OSError:
        return


def _read_pull_track(settings: Settings) -> dict[str, Any]:
    try:
        raw = json.loads(_track_path(settings).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_pull_track(settings: Settings, track: dict[str, Any]) -> None:
    path = _track_path(settings)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(track, ensure_ascii=False), encoding="utf-8")
    except OSError:
        return


def clear_pull_track(settings: Settings) -> None:
    try:
        _track_path(settings).unlink(missing_ok=True)
    except OSError:
        return


def pull_restart_note_active(settings: Settings | None = None, *, now: datetime | None = None) -> bool:
    """True for a short window after a Node Offline / reallocation restart."""
    settings = settings or get_settings()
    until = _parse_time(_read_pull_track(settings).get("restart_until"))
    if until is None:
        return False
    return _utc_now(now) < until


def _line_node_offline(text: str) -> bool:
    lower = text.lower()
    return "node offline" in lower or "instance interrupted" in lower


def recent_node_offline(settings: Settings | None = None) -> bool:
    """Best-effort Salad log probe; cached so /api/gpu polls do not hammer log-entries."""
    global _node_offline_probe
    settings = settings or get_settings()
    mono = time.monotonic()
    cached_at, cached_hit = _node_offline_probe
    if mono - cached_at < NODE_OFFLINE_PROBE_S:
        return cached_hit
    hit = False
    try:
        rows = container_logs(settings, since=timedelta(minutes=45))
        for line in rows.get("lines") or []:
            if isinstance(line, str) and _line_node_offline(line):
                hit = True
                break
    except Exception:  # noqa: BLE001 — probe must never break status
        hit = False
    _node_offline_probe = (mono, hit)
    return hit


def note_pull_progress(
    state: GroupState,
    settings: Settings | None = None,
    *,
    now: datetime | None = None,
    probe_logs: bool = True,
) -> bool:
    """Track creating/allocating dips. True when the current image pull restarted."""
    settings = settings or get_settings()
    current = _utc_now(now)
    if not state.still_pulling:
        clear_pull_track(settings)
        return False

    track = _read_pull_track(settings)
    prev_creating = int(track.get("creating_count") or 0)
    prev_allocating = int(track.get("allocating_count") or 0)
    saw_dip = bool(track.get("saw_dip"))
    if state.creating_count == 0 and prev_creating > 0:
        saw_dip = True
    if state.allocating_count > 0 and prev_creating > 0 and state.creating_count == 0:
        saw_dip = True

    restarted = False
    # Creating rose again after a dip → new node is pulling the image.
    if saw_dip and state.creating_count > 0:
        restarted = True
    # Allocating after a dip with Node Offline in recent Salad logs.
    elif (
        saw_dip
        and state.allocating_count > 0
        and prev_allocating == 0
        and state.creating_count == 0
        and probe_logs
        and recent_node_offline(settings)
    ):
        restarted = True

    remembered = _read_pull_stamp(settings)
    if (
        state.start_time is not None
        and remembered is not None
        and state.start_time > remembered + timedelta(seconds=30)
    ):
        restarted = True

    if restarted:
        clear_pull_stamp(settings)
        _write_pull_stamp(settings, current)
        track = {
            "creating_count": state.creating_count,
            "allocating_count": state.allocating_count,
            "saw_dip": False,
            "restart_until": (current + timedelta(seconds=PULL_RESTART_NOTE_S)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        }
        _write_pull_track(settings, track)
        log.info("salad.pull_restart", status=state.status, creating=state.creating_count)
        return True

    track["creating_count"] = state.creating_count
    track["allocating_count"] = state.allocating_count
    track["saw_dip"] = saw_dip
    if "restart_until" in track and not pull_restart_note_active(settings, now=current):
        track.pop("restart_until", None)
    _write_pull_track(settings, track)
    return False


def pull_started_at(
    state: GroupState,
    settings: Settings | None = None,
    *,
    now: datetime | None = None,
    probe_logs: bool = True,
) -> datetime | None:
    """Wall clock when the current image pull began. None once the replica is up or the group is down."""
    settings = settings or get_settings()
    current = _utc_now(now)
    if not state.still_pulling:
        clear_pull_stamp(settings)
        clear_pull_track(settings)
        return None
    note_pull_progress(state, settings, now=current, probe_logs=probe_logs)
    remembered = _read_pull_stamp(settings)
    # After Node Offline the group start_time often stays old — prefer a newer local stamp.
    if remembered is not None and (state.start_time is None or remembered >= state.start_time):
        return remembered
    if state.start_time is not None:
        _write_pull_stamp(settings, state.start_time)
        return state.start_time
    _write_pull_stamp(settings, current)
    return current


def _format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    if total < 60:
        return f"{total} с"
    return f"{total // 60} мин {total % 60:02d} с"


def _soft_ratio(phase: int, *, phases: int, elapsed: float, soft_s: float) -> float:
    phase = max(1, min(phase, phases))
    base = (phase - 1) / phases
    width = 1.0 / phases
    soft = min(0.9, elapsed / soft_s) if soft_s > 0 else 0.0
    return round(base + width * soft, 3)


def _launch_title(state: GroupState, settings: Settings | None = None) -> str:
    if state.status == "pending":
        return PHASE_NODE
    if state.status == "deploying" or state.creating_count > 0:
        if pull_restart_note_active(settings):
            return PHASE_PULL_RESTART
        return PHASE_PULL
    if state.allocating_count > 0:
        if pull_restart_note_active(settings):
            return PHASE_PULL_RESTART
        return PHASE_ALLOC
    if state.status == "running":
        return "Узел запущен"
    if state.status in START_READY:
        return LAUNCH_STATUS
    return f"Запуск ({state.status or '…'})"


def _prep(
    title: str,
    phase: int,
    *,
    started: float,
    phase_started: float,
    clock: Callable[[], float],
    soft_s: float,
    milestone: bool = False,
    extra: str = "",
    elapsed: float | None = None,
) -> PrepStatus:
    now = clock()
    shown = elapsed if elapsed is not None else now - started
    detail = _format_elapsed(shown)
    if extra:
        detail = f"{extra} · {detail}"
    return PrepStatus(
        title=title,
        phase=phase,
        phases=PREP_PHASES,
        ratio=_soft_ratio(phase, phases=PREP_PHASES, elapsed=now - phase_started, soft_s=soft_s),
        detail=detail,
        milestone=milestone,
    )


def _api_unreachable(exc: BaseException) -> bool:
    return isinstance(exc, SaladProblem) and str(exc) == SALAD_UNREACHABLE


def prepare_for_chat(
    settings: Settings | None = None,
    *,
    pause: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Generator[PrepStatus | WireTrace, None, str]:
    """Start the group, warm qwen inside it, and return the chat base URL.

    Yields live PrepStatus lines for the bottom chat. The caller streams them
    so a long image pull does not look stuck.
    """
    settings = require_configured(settings)
    _touch(settings)
    started = clock()
    phase_started = started
    last_title = ""

    def emit(
        title: str,
        phase: int,
        *,
        soft_s: float,
        extra: str = "",
        force_milestone: bool = False,
        elapsed: float | None = None,
    ) -> PrepStatus:
        nonlocal last_title, phase_started
        milestone = force_milestone or title != last_title
        if milestone:
            phase_started = clock()
            last_title = title
        return _prep(
            title,
            phase,
            started=started,
            phase_started=phase_started,
            clock=clock,
            soft_s=soft_s,
            milestone=milestone,
            extra=extra,
            elapsed=elapsed,
        )

    seen_wire: set[str] = set()
    group_path = _group_public_path(settings)

    def wire(method: str, path: str, result: str) -> WireTrace | None:
        key = f"{method} {path} {result}"
        if key in seen_wire:
            return None
        seen_wire.add(key)
        return WireTrace(method, path, result[:160])

    def fetch_group(
        *,
        attempts: int = POLL_API_ATTEMPTS,
        pulling: bool = False,
    ) -> Generator[PrepStatus | WireTrace, None, GroupState]:
        exhausted = API_DOWN_WHILE_PULL if pulling else API_DOWN
        for attempt in range(1, attempts + 1):
            try:
                found = get_group(settings)
            except SaladProblem as exc:
                if not _api_unreachable(exc):
                    raise
                traced = wire("GET", group_path, "нет связи")
                if traced:
                    yield traced
                if attempt >= attempts:
                    raise SaladProblem(exhausted) from None
                yield emit(
                    PHASE_API,
                    2,
                    soft_s=POLL_S * attempts,
                    extra=f"попытка {attempt}",
                )
                pause(POLL_S)
                continue
            traced = wire("GET", group_path, f"200 {found.status}")
            if traced:
                yield traced
            return found
        raise SaladProblem(exhausted)

    def call_action(
        action: Callable[[], Any],
        *,
        attempts: int = ACTION_API_ATTEMPTS,
        exhausted: str = API_DOWN,
    ) -> Generator[PrepStatus, None, Any]:
        for attempt in range(1, attempts + 1):
            try:
                return action()
            except SaladProblem as exc:
                if exc.status_code == 409 or not _api_unreachable(exc):
                    raise
                if attempt >= attempts:
                    raise SaladProblem(exhausted) from None
                yield emit(
                    PHASE_API,
                    2,
                    soft_s=POLL_S * attempts,
                    extra=f"попытка {attempt}",
                )
                pause(POLL_S)
        raise SaladProblem(exhausted)

    state = yield from fetch_group()
    patch_after_pull = False
    if needs_gateway_patch(settings, state):
        if state.still_pulling:
            patch_after_pull = True
        else:
            yield emit(PHASE_PATCH, 1, soft_s=60, force_milestone=True)
            known = state
            state = yield from call_action(lambda: patch_gateway(settings, known))
            _touch(settings)
    if state.status != "running":
        if state.status in START_READY:
            yield emit(SEND_START, 2, soft_s=60, force_milestone=True)
            start_path = f"{group_path}/start"
            try:
                yield from call_action(
                    lambda: request_start(settings),
                    exhausted=START_NOT_SENT,
                )
            except SaladProblem as exc:
                traced = wire("POST", start_path, str(exc)[:160])
                if traced:
                    yield traced
                if exc.status_code != 409:
                    raise
            else:
                traced = wire("POST", start_path, "202")
                if traced:
                    yield traced
            yield emit(LAUNCH_STATUS, 2, soft_s=START_WAIT_S, force_milestone=True)
            state = yield from fetch_group()
            _touch(settings)
        if state.still_pulling:
            # Seed creating/allocating so a later dip → recreate counts as Node Offline restart.
            note_pull_progress(state, settings, probe_logs=False)
        wait_started = clock()
        non_pull_started: float | None = None
        misses = 0
        while state.status != "running" and not state.replica_ready:
            if state.status == "failed":
                raise SaladProblem("Запуск видеокарты на Salad не удался.")
            pause(POLL_S)
            try:
                token = _poll_timeout.set(POLL_TIMEOUT)
                try:
                    state = get_group(settings)
                finally:
                    _poll_timeout.reset(token)
            except SaladProblem as exc:
                if not _api_unreachable(exc):
                    raise
                misses += 1
                yield WireTrace("GET", group_path, f"нет связи ({misses})")
                if clock() - wait_started > PULL_WAIT_S:
                    raise SaladProblem(API_DOWN_WHILE_PULL) from None
                yield emit(PHASE_API, 2, soft_s=60, extra="нет связи с Salad")
                continue
            traced = wire("GET", group_path, f"200 {state.status}")
            if traced:
                yield traced
            _touch(settings)
            if state.status == "running" or state.replica_ready:
                break
            if state.status == "failed":
                raise SaladProblem("Запуск видеокарты на Salad не удался.")
            if state.still_pulling:
                non_pull_started = None
                if clock() - wait_started > PULL_WAIT_S:
                    raise SaladProblem(
                        "Образ всё ещё качается на узел. Подождите и спросите ещё раз — Start уже идёт."
                    )
                restarted = note_pull_progress(state, settings, probe_logs=True)
                anchor = pull_started_at(state, settings, probe_logs=False)
                pull_for = None
                if anchor is not None:
                    pull_for = max(0.0, (datetime.now(timezone.utc) - anchor).total_seconds())
                title = _launch_title(state, settings)
                yield emit(
                    title,
                    2,
                    soft_s=PULL_WAIT_S,
                    extra=state.status,
                    elapsed=pull_for,
                    force_milestone=restarted,
                )
            else:
                if non_pull_started is None:
                    non_pull_started = clock()
                if clock() - non_pull_started > START_WAIT_S:
                    raise SaladProblem("Видеокарта не успела запуститься")
                yield emit(
                    _launch_title(state, settings),
                    2,
                    soft_s=START_WAIT_S,
                    extra=state.status,
                )
    if patch_after_pull and needs_gateway_patch(settings, state):
        yield emit(PHASE_PATCH, 1, soft_s=60, force_milestone=True)
        known = state
        state = yield from call_action(lambda: patch_gateway(settings, known))
        _touch(settings)
    origin = gateway_origin(state.dns)
    if not origin:
        raise SaladProblem("Salad не вернул адрес группы")
    model = _model_name(settings)
    deadline = clock() + START_WAIT_S + WARM_WAIT_S
    last_kick = 0.0
    while True:
        up = _ollama_up(origin, settings)
        loaded = _model_loaded(origin, settings, model) if up else False
        ollama_result = (
            "200, модель в памяти" if up and loaded else ("200, жду модель" if up else "нет связи")
        )
        traced = wire("GET", f"{origin}/", ollama_result)
        if traced:
            yield traced
        if up and loaded:
            break
        if clock() > deadline:
            raise SaladProblem(
                "Модель не успела прогреться" if up else "Видеокарта не успела запуститься"
            )
        if up:
            present = _model_present(origin, settings, model)
            if present is False:
                raise SaladProblem(
                    f"Модели {model} нет на узле — проверьте образ GPU / AGENT_MODEL"
                )
            now = clock()
            if last_kick == 0.0 or now - last_kick >= KICK_INTERVAL_S:
                kick_result = _kick_model_load(origin, settings, model)
                last_kick = now
                kicked = wire("POST", f"{origin}/api/generate", kick_result)
                if kicked:
                    yield kicked
            yield emit(PHASE_MODEL, 4, soft_s=WARM_WAIT_S)
        else:
            yield emit(PHASE_OLLAMA, 3, soft_s=START_WAIT_S, extra=state.status or "")
        pause(POLL_S)
        state = yield from fetch_group()
        origin = gateway_origin(state.dns) or origin
        _touch(settings)
    base = chat_base_url(state)
    if not base:
        raise SaladProblem("Salad не вернул адрес группы")
    return base


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def container_logs(
    settings: Settings | None = None,
    *,
    since: timedelta | None = None,
    empty_reason: str | None = None,
) -> dict[str, Any]:
    """Stdout/stderr of the GPU group, plus instance start/probe events. Never includes the API key."""
    settings = settings or get_settings()
    if not configured(settings):
        return {"available": False, "reason": "Salad не настроен", "lines": []}
    org, project, group = _names(settings)
    end = datetime.now(timezone.utc)
    start = end - (since if since is not None else timedelta(hours=1))
    query = (
        '(resource.type = "container" or resource.type = "instance_controller")'
        f' and resource.labels.project_name = "{_label(project)}"'
        f' and resource.labels.container_group_name = "{_label(group)}"'
    )
    url = f"{SALAD_API_ROOT}/organizations/{quote(org, safe='')}/log-entries"
    body = {
        "sort_order": "desc",
        "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_time": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        # Log query pages are 1–100 entries.
        "page_size": 100,
        "query": query,
    }
    try:
        with http_client(settings, timeout=TIMEOUT) as client:
            response = client.post(url, headers=_headers(settings), json=body)
    except httpx.RequestError:
        log.warning("salad.logs_failed")
        return {"available": False, "reason": SALAD_UNREACHABLE, "lines": []}
    if response.status_code >= 400:
        payload: Any = None
        try:
            payload = response.json()
        except ValueError:
            payload = None
        return {"available": False, "reason": _safe_detail(response.status_code, payload), "lines": []}
    try:
        payload = response.json()
    except ValueError:
        return {"available": False, "reason": "Salad вернул не JSON", "lines": []}
    items = payload.get("items") if isinstance(payload, dict) else None
    lines: list[str] = []
    if isinstance(items, list):
        for item in reversed(items):
            if not isinstance(item, dict):
                continue
            text = item.get("text_log")
            if isinstance(text, str) and text.strip():
                lines.append(text.rstrip()[:2000])
                continue
            blob = item.get("json_log")
            if blob is None:
                continue
            raw = blob if isinstance(blob, str) else json.dumps(blob, ensure_ascii=False)
            lines.append(raw[:500])
    if not lines:
        return {
            "available": True,
            "reason": empty_reason or "за последний час логов нет",
            "lines": [],
        }
    return {"available": True, "reason": "", "lines": lines}


def require_configured(settings: Settings | None = None) -> Settings:
    settings = settings or get_settings()
    if not configured(settings):
        raise SaladProblem(
            "Salad не настроен — задайте SALAD_API_KEY, SALAD_ORGANIZATION, "
            "SALAD_PROJECT, SALAD_CONTAINER_GROUP",
            status_code=503,
        )
    return settings


def get_group(settings: Settings | None = None) -> GroupState:
    settings = require_configured(settings)
    url = _group_url(settings)
    try:
        with http_client(settings, timeout=_poll_timeout.get() or TIMEOUT) as client:
            response = client.get(url, headers=_headers(settings))
            if response.status_code >= 400:
                _raise_http(response)
            payload = response.json()
    except httpx.RequestError:
        log.warning("salad.get_failed")
        raise SaladProblem(SALAD_UNREACHABLE) from None
    except ValueError:
        raise SaladProblem("Salad вернул не JSON") from None
    if not isinstance(payload, dict):
        raise SaladProblem("Salad вернул не объект группы")
    return _parse_state(payload)


def _post_action(settings: Settings, action: str) -> None:
    url = f"{_group_url(settings)}/{action}"
    org, project, group = _names(settings)
    log.info("salad.action", action=action, organization=org, project=project, group=group)
    try:
        with http_client(settings, timeout=TIMEOUT) as client:
            response = client.post(url, headers=_headers(settings))
            if response.status_code not in {200, 202}:
                _raise_http(response)
    except httpx.RequestError:
        log.warning("salad.action_failed", action=action)
        raise SaladProblem(SALAD_UNREACHABLE) from None


def request_start(settings: Settings | None = None) -> None:
    """POST /start only. The caller already knows the group is stopped."""
    settings = require_configured(settings)
    _post_action(settings, "start")


def start_group(settings: Settings | None = None) -> GroupState:
    settings = require_configured(settings)
    current = get_group(settings)
    if current.status not in START_READY:
        raise SaladProblem(
            "Группа уже запущена или стартует",
            status_code=409,
        )
    _post_action(settings, "start")
    return get_group(settings)


def stop_group(settings: Settings | None = None) -> GroupState:
    settings = require_configured(settings)
    current = get_group(settings)
    if current.status not in STOP_READY:
        raise SaladProblem(
            "Группа уже остановлена",
            status_code=409,
        )
    _post_action(settings, "stop")
    return get_group(settings)
