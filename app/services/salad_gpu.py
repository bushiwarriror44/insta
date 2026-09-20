"""Salad Cloud container-group Start/Stop for the admin panel.

The panel talks to the Salad Public API so the owner does not need the
Salad portal for day-to-day GPU hours. Running bills; Stop does not.
Start after Stop pulls the image onto a node again.

The API key never leaves this module in logs or raised messages.
"""

from __future__ import annotations

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
    return GroupState(
        status=status,
        allocating_count=int(counts.get("allocating_count") or 0),
        creating_count=int(counts.get("creating_count") or 0),
        running_count=int(counts.get("running_count") or 0),
        stopping_count=int(counts.get("stopping_count") or 0),
        detail=str(state.get("description") or "").strip()[:240],
    )


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
