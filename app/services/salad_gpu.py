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
from typing import Any
from urllib.parse import quote

import httpx

from app.config import Settings, get_settings
from app.logging_setup import get_logger
from app.services.http import client as http_client

log = get_logger(__name__)

SALAD_API_ROOT = "https://api.salad.com/api/public"
TIMEOUT = 30.0

START_READY = frozenset({"stopped", "succeeded", "failed"})
STOP_READY = frozenset({"running", "pending", "deploying"})
GATEWAY_PORT = 11434
WARMUP_MARKER = "gpu-warmup"
LAUNCH_STATUS = "Запускаю видеокарту, подождите"
WARM_STATUS = "Прогреваю модель, подождите"
POLL_S = 5.0
START_WAIT_S = 25 * 60
WARM_WAIT_S = 20 * 60
_MODEL_NAME = re.compile(r"[A-Za-z0-9_.:-]{1,80}")


class SaladProblem(Exception):
    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


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


def warmup_script(model: str) -> str:
    """In-container warmup. The public gateway cuts requests at ~100s."""
    body = json.dumps(
        {"model": model, "prompt": "hi", "stream": False, "keep_alive": "30m"}
    )
    py = (
        "import urllib.request; urllib.request.urlopen(urllib.request.Request("
        '"http://127.0.0.1:11434/api/generate", data='
        + json.dumps(body)
        + '.encode(), headers={"Content-Type": "application/json"}), timeout=600).read()'
    )
    return (
        f"# {WARMUP_MARKER}\n"
        "set -eu\n"
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


def needs_gateway_patch(state: GroupState) -> bool:
    return WARMUP_MARKER not in _command_text(state) or state.port != GATEWAY_PORT


def patch_gateway(settings: Settings, state: GroupState) -> GroupState:
    """Install the warmup command and chat port once. Salad restarts the replica."""
    settings = require_configured(settings)
    body: dict[str, Any] = {}
    if WARMUP_MARKER not in _command_text(state):
        body["container"] = {
            "command": ["/bin/bash", "-c", warmup_script(_model_name(settings))]
        }
    if state.port != GATEWAY_PORT:
        body["networking"] = {"port": GATEWAY_PORT}
    if not body:
        return state
    url = _group_url(settings)
    log.info("salad.patch_gateway", port=GATEWAY_PORT)
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


def prepare_for_chat(
    settings: Settings | None = None,
    *,
    pause: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Generator[str, None, str]:
    """Start the group, warm qwen inside it, and return the chat base URL.

    Status lines are for the bottom chat. The caller keeps streaming them
    so a long image pull does not look stuck.
    """
    settings = require_configured(settings)
    state = get_group(settings)
    _touch(settings)
    if needs_gateway_patch(state):
        yield WARM_STATUS
        state = patch_gateway(settings, state)
        _touch(settings)
    if state.status != "running":
        if state.status in START_READY:
            yield LAUNCH_STATUS
            try:
                state = start_group(settings)
            except SaladProblem as exc:
                if exc.status_code != 409:
                    raise
                state = get_group(settings)
            _touch(settings)
        deadline = clock() + START_WAIT_S
        while state.status != "running":
            if clock() > deadline or state.status == "failed":
                raise SaladProblem("Видеокарта не успела запуститься")
            yield LAUNCH_STATUS
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
        yield WARM_STATUS if up else LAUNCH_STATUS
        pause(POLL_S)
        state = get_group(settings)
        origin = gateway_origin(state.dns) or origin
        _touch(settings)
    base = chat_base_url(state)
    if not base:
        raise SaladProblem("Salad не вернул адрес группы")
    return base


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
