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
from collections.abc import Callable, Generator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
LAUNCH_STATUS = "Запускаю видеокарту, подождите"
WARM_STATUS = "Прогреваю модель, подождите"
PHASE_PATCH = "Настраиваю шлюз"
PHASE_NODE = "Жду узел"
PHASE_PULL = "Качается образ на узел"
PHASE_ALLOC = "Выделяю GPU"
PHASE_OLLAMA = "Жду Ollama"
PHASE_MODEL = "Гружу модель в память"
POLL_S = 5.0
START_WAIT_S = 25 * 60
PULL_WAIT_S = 90 * 60
WARM_WAIT_S = 20 * 60
PREP_PHASES = 4
_MODEL_NAME = re.compile(r"[A-Za-z0-9_.:-]{1,80}")


class SaladProblem(Exception):
    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


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

    @property
    def billing(self) -> bool:
        return self.status == "running"

    @property
    def still_pulling(self) -> bool:
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
    ):
        return True
    if patch_configured(settings) and WAN_ASYNC_PATCH_MARKER not in text:
        return True
    return False


def warmup_script(model: str, settings: Settings | None = None) -> str:
    """In-container warmup. The public gateway cuts requests at ~100s."""
    settings = settings or get_settings()
    curl_patch = patch_curl_shell(settings)
    header = f"# {WARMUP_MARKER} {IPV6_MARKER} {WAN_DEPS_MARKER}"
    if curl_patch:
        header += f" {WAN_ASYNC_PATCH_MARKER}"
    body = json.dumps(
        {"model": model, "prompt": "hi", "stream": False, "keep_alive": "30m"}
    )
    py = (
        "import urllib.request; urllib.request.urlopen(urllib.request.Request("
        '"http://127.0.0.1:11434/api/generate", data='
        + json.dumps(body)
        + '.encode(), headers={"Content-Type": "application/json"}), timeout=600).read()'
    )
    patch_lines = f"{curl_patch}\n" if curl_patch else ""
    return (
        f"{header}\n"
        "set -eu\n"
        "conf=/etc/nginx/conf.d/salad.conf\n"
        "if [ -f \"$conf\" ] && ! grep -q '\\[::\\]:8080' \"$conf\"; then\n"
        "  sed -i 's/listen 8080 default_server;/listen [::]:8080 default_server ipv6only=off;/' \"$conf\"\n"
        "fi\n"
        "python -m pip install -q dashscope\n"
        f"{patch_lines}"
        "/opt/gpu/start.sh &\n"
        "spid=$!\n"
        "(\n"
        "  i=0\n"
        '  while [ "$i" -lt 90 ]; do\n'
        "    curl -sf http://127.0.0.1:11434/ >/dev/null && break\n"
        "    i=$((i+1))\n"
        "    sleep 2\n"
        "  done\n"
        f"  python -c '{py}'\n"
        ") >/tmp/warmup.log 2>&1 &\n"
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
        raise SaladProblem("Salad не отвечает") from None
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


def _model_loaded(origin: str, settings: Settings, model: str) -> bool:
    response = _get(origin, "/api/ps", settings)
    if response is None or response.status_code >= 400:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    rows = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return False
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or row.get("model") or "")
        if name == model or name.startswith(f"{model}:"):
            return True
    return False


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


def _launch_title(state: GroupState) -> str:
    if state.status == "pending":
        return PHASE_NODE
    if state.status == "deploying" or state.creating_count > 0:
        return PHASE_PULL
    if state.allocating_count > 0:
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
) -> PrepStatus:
    now = clock()
    elapsed = now - started
    detail = _format_elapsed(elapsed)
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


def prepare_for_chat(
    settings: Settings | None = None,
    *,
    pause: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Generator[PrepStatus, None, str]:
    """Start the group, warm qwen inside it, and return the chat base URL.

    Yields live PrepStatus lines for the bottom chat. The caller streams them
    so a long image pull does not look stuck.
    """
    settings = require_configured(settings)
    state = get_group(settings)
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
        )

    if needs_gateway_patch(settings, state):
        yield emit(PHASE_PATCH, 1, soft_s=60, force_milestone=True)
        state = patch_gateway(settings, state)
        _touch(settings)
    if state.status != "running":
        if state.status in START_READY:
            yield emit(_launch_title(state), 2, soft_s=START_WAIT_S, force_milestone=True)
            try:
                state = start_group(settings)
            except SaladProblem as exc:
                if exc.status_code != 409:
                    raise
                state = get_group(settings)
            _touch(settings)
        wait_started = clock()
        non_pull_started: float | None = None
        while state.status != "running":
            if state.status == "failed":
                raise SaladProblem("Запуск видеокарты на Salad не удался.")
            if state.still_pulling:
                non_pull_started = None
                if clock() - wait_started > PULL_WAIT_S:
                    raise SaladProblem(
                        "Образ всё ещё качается на узел. Подождите и спросите ещё раз — Start уже идёт."
                    )
                soft = PULL_WAIT_S
            else:
                if non_pull_started is None:
                    non_pull_started = clock()
                if clock() - non_pull_started > START_WAIT_S:
                    raise SaladProblem("Видеокарта не успела запуститься")
                soft = START_WAIT_S
            yield emit(_launch_title(state), 2, soft_s=soft, extra=state.status)
            pause(POLL_S)
            state = get_group(settings)
            _touch(settings)
    origin = gateway_origin(state.dns)
    if not origin:
        raise SaladProblem("Salad не вернул адрес группы")
    model = _model_name(settings)
    deadline = clock() + START_WAIT_S + WARM_WAIT_S
    while True:
        up = _ollama_up(origin, settings)
        if up and _model_loaded(origin, settings, model):
            break
        if clock() > deadline:
            raise SaladProblem(
                "Модель не успела прогреться" if up else "Видеокарта не успела запуститься"
            )
        if up:
            yield emit(PHASE_MODEL, 4, soft_s=WARM_WAIT_S)
        else:
            yield emit(PHASE_OLLAMA, 3, soft_s=START_WAIT_S, extra=state.status or "")
        pause(POLL_S)
        state = get_group(settings)
        origin = gateway_origin(state.dns) or origin
        _touch(settings)
    base = chat_base_url(state)
    if not base:
        raise SaladProblem("Salad не вернул адрес группы")
    return base


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def container_logs(settings: Settings | None = None) -> dict[str, Any]:
    """Stdout/stderr of the GPU group for the last hour. Never includes the API key."""
    settings = settings or get_settings()
    if not configured(settings):
        return {"available": False, "reason": "Salad не настроен", "lines": []}
    org, project, group = _names(settings)
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=1)
    query = (
        'resource.type = "container"'
        f' and resource.labels.project_name = "{_label(project)}"'
        f' and resource.labels.container_group_name = "{_label(group)}"'
    )
    url = f"{SALAD_API_ROOT}/organizations/{quote(org, safe='')}/log-entries"
    body = {
        "sort_order": "desc",
        "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_time": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "page_size": 50,
        "query": query,
    }
    try:
        with http_client(settings, timeout=TIMEOUT) as client:
            response = client.post(url, headers=_headers(settings), json=body)
    except httpx.RequestError:
        log.warning("salad.logs_failed")
        return {"available": False, "reason": "Salad не отвечает", "lines": []}
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
        return {"available": True, "reason": "за последний час логов нет", "lines": []}
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
        with http_client(settings, timeout=TIMEOUT) as client:
            response = client.get(url, headers=_headers(settings))
    except httpx.RequestError:
        log.warning("salad.get_failed")
        raise SaladProblem("Salad не отвечает") from None
    if response.status_code >= 400:
        _raise_http(response)
    try:
        payload = response.json()
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
    except httpx.RequestError:
        log.warning("salad.action_failed", action=action)
        raise SaladProblem("Salad не отвечает") from None
    if response.status_code not in {200, 202}:
        _raise_http(response)


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
